# Sprint Bug Fix Analyzer — Architecture

อธิบายการทำงานของทั้งโปรเจคตั้งแต่ต้นจนจบ

---

## ภาพรวม (Overview)

```
.env (config)
     │
     ▼
sprint_bug_analyzer.py  ← จุดเริ่มต้น (orchestrator)
     │
     ├─[1]─► azure_client.py          ดึง commits + diff จาก Azure DevOps
     │
     ├─[2]─► analyzer (เลือก 1 อัน)
     │         ├── analyzers/keyword.py    (regex rules, ฟรี)
     │         ├── analyzers/gemini.py     (Google Gemini API)
     │         ├── analyzers/openai.py     (OpenAI GPT API)
     │         ├── analyzers/ollama.py     (Local LLM)
     │         └── analyzers/claude.py     (Anthropic Claude API)
     │
     └─[3]─► excel_reporter.py        สร้างไฟล์ Excel multi-sheet
                  │
                  └── output/bug_report_*.xlsx
```

---

## ขั้นตอนการทำงาน (3 Steps)

### Step 1 — ดึงข้อมูลจาก Azure DevOps

**ไฟล์:** `azure_client.py`

**1.1 ดึงรายการ commits (`get_commits`)**

เรียก Azure DevOps REST API:
```
GET https://dev.azure.com/{org}/{project}/_apis/git/repositories/{repo}/commits
    ?searchCriteria.fromDate=2025-01-01T00:00:00Z
    &searchCriteria.toDate=2025-01-14T23:59:59Z
    &$top=100&$skip=0
```
- ดึงทีละ 100 commits (pagination) จนหมด
- แต่ละ commit เก็บ: `commit_id`, `author`, `author_email`, `date`, `message`
- ถ้ากำหนด `AZURE_BRANCH` จะกรองเฉพาะ branch นั้น

**1.2 ดึง diff ของแต่ละ commit (`enrich_commits`)**

สำหรับแต่ละ commit:
1. เรียก `/commits/{id}/changes` → ได้ list ของไฟล์ที่เปลี่ยน
2. สำหรับแต่ละไฟล์ ดึง content ก่อน commit (parent) และหลัง commit
3. สร้าง **unified diff** ด้วย `difflib.unified_diff` (format เดียวกับ `git diff`)
4. ตัด diff ที่ยาวเกิน 8,000 ตัวอักษร เพื่อประหยัด token

> **Keyword mode ข้ามขั้นตอนนี้** — ดึงแค่รายชื่อไฟล์ (ไม่ดึง content) เพราะไม่ต้องอ่าน diff

**Output:** list ของ `CommitInfo` objects

```python
@dataclass
class CommitInfo:
    commit_id: str        # full SHA hash
    author: str           # ชื่อผู้ commit
    author_email: str
    date: str             # ISO datetime
    message: str          # commit message
    files_changed: list[str]  # รายชื่อไฟล์
    diff_text: str        # unified diff (ถ้าดึงมา)
```

---

### Step 2 — วิเคราะห์แต่ละ commit

รับ `list[CommitInfo]` → คืน `list[CommitAnalysis]`

**Output ของทุก mode มีรูปแบบเดียวกัน:**

```python
@dataclass
class CommitAnalysis:
    commit_id: str
    is_bug_fix: bool          # True/False
    confidence: Confidence    # High / Medium / Low
    category: Category        # Bug Fix / Feature / Refactor / Chore / Unclear
    bug_type: BugType         # Logic Error / Crash / Security / ...
    severity: Severity        # Critical / Major / Minor / N/A
    reasoning: str            # คำอธิบาย
    files_changed: list[str]
    error: str                # ถ้า analyze ล้มเหลว
```

---

#### Mode A: Keyword (`analyzers/keyword.py`)

วิธีทำงาน: ใช้ **regex pattern matching** บน commit message และ diff

**3 Tier ของ signal:**

```
Tier 1 — HIGH confidence
  ├── Conventional commit prefix:  fix:  hotfix(scope):  patch:
  ├── Issue reference:              fixes #123  closes #456
  └── Tech bug terms:              null pointer / race condition / deadlock / off-by-one

Tier 2 — MEDIUM confidence
  ├── Bug/fix keywords:            fix / bug / revert / แก้ / ซ่อม
  ├── AI-style verb + problem:     resolve X failure / prevent crash / handle missing
  └── Edge case language:          edge case / corner case / boundary condition

Tier 3 — LOW confidence (diff เท่านั้น)
  ├── null check เพิ่มใน diff:    if (x == null) / x ?? default
  └── try/catch เพิ่มใน diff
```

**Confidence upgrade:**
- ถ้าจาก Tier 2 แต่ diff มี null check หรือ try/catch → upgrade เป็น High

**Bug Type classification:**
ดูจาก keyword ในชื่อไฟล์ + commit message:
- `security / auth / token` → Security
- `crash / exception / null pointer` → Crash
- `slow / memory leak / timeout` → Performance
- `ui / layout / css / render` → UI Bug
- `db / sql / migration` → Data
- `api / webhook / endpoint` → Integration
- อื่นๆ → Logic Error

---

#### Mode B: Gemini (`analyzers/gemini.py`)

วิธีทำงาน: ส่ง commit message + diff ให้ Google Gemini วิเคราะห์

**รองรับ 2 แบบ:**
- **AI Studio** — ใช้ `GOOGLE_API_KEY` (มี free quota)
- **Vertex AI** — ใช้ `gcloud auth` + Google Cloud credits

**Flow:**
```
CommitInfo
    │
    ▼
สร้าง prompt (commit message + files + diff)
    │
    ▼
Gemini API (response_mime_type="application/json" + response_schema)
    │  ← บังคับให้ตอบเป็น JSON ตาม schema ที่กำหนด
    ▼
parse JSON → CommitAnalysis
```

**JSON Schema ที่กำหนดให้ Gemini ตอบ:**
```json
{
  "is_bug_fix": boolean,
  "confidence": "High" | "Medium" | "Low",
  "category": "Bug Fix" | "Feature" | "Refactor" | "Chore" | "Unclear",
  "bug_type": "Logic Error" | "Crash" | "Security" | ...,
  "severity": "Critical" | "Major" | "Minor" | "N/A",
  "reasoning": "string"
}
```

**Error handling:**
- Invalid API key → หยุดทันที (abort batch)
- Permission denied → หยุดทันที
- Rate limit (429) → sleep แล้ว retry สูงสุด 2 ครั้ง
- Error อื่น → บันทึก fallback แล้ววิเคราะห์ commit ถัดไปต่อ

---

#### Mode C: Ollama (`analyzers/ollama.py`)

วิธีทำงาน: เหมือน Gemini แต่เรียก local API ที่รันบนเครื่องตัวเอง

```
CommitInfo
    │
    ▼
POST http://localhost:11434/api/chat
    {
      "model": "qwen2.5:3b",
      "format": "json",       ← บังคับให้ตอบ JSON
      "stream": false,
      "messages": [system_prompt, user_message]
    }
    │
    ▼
parse JSON → CommitAnalysis
```

**หมายเหตุ:**
- System prompt ลงท้ายด้วย `/no_think` เพื่อปิด thinking mode ของ Qwen 3
- ตรวจสอบ connection และ model ก่อนเริ่ม batch (fail fast)
- Timeout 120 วินาทีต่อ request (local model ช้ากว่า cloud)

---

#### Mode D: Claude (`analyzers/claude.py`)

วิธีทำงาน: ใช้ Anthropic API พร้อม **forced tool-use**

```
CommitInfo
    │
    ▼
Anthropic API (tools=[classify_commit_tool])
    │  ← บังคับให้ใช้ tool (ไม่ตอบ free-form text)
    ▼
tool_use block → CommitAnalysis
```

**ทำไมต้องใช้ tool-use:**
ถ้าไม่บังคับ Claude อาจตอบเป็น prose แทน JSON — tool-use รับประกันว่าได้ structured output เสมอ

---

## Prompt ที่ส่งให้แต่ละ Model

ทุก mode ส่ง prompt 2 ส่วน: **System Prompt** (กฎและบทบาท) + **User Message** (ข้อมูล commit จริง)

### User Message (เหมือนกันทุก mode)

```
Commit ID: abc1234
Author: John Doe <john@example.com>
Date: 2025-01-10
Message: fix(auth): resolve authentication failure when session token is missing

Files changed:
/src/auth/tokenService.ts
/src/middleware/authGuard.ts

Diff:
--- a/src/auth/tokenService.ts
+++ b/src/auth/tokenService.ts
@@ -12,6 +12,9 @@
 export function validateToken(token: string) {
+  if (!token) {
+    throw new AuthError('Token is required');
+  }
   return jwt.verify(token, SECRET_KEY);
```

---

### System Prompt: Ollama

สั้นที่สุด — model เล็ก เข้าใจ instruction ง่ายกว่า ต้องบอก format JSON ตรงๆ และมี example

```
You are a software engineer analyzing Git commits to classify them as bug fixes or not.

Respond ONLY with a JSON object matching this exact schema — no explanation, no markdown:

{
  "is_bug_fix": <true or false>,
  "confidence": <"High" | "Medium" | "Low">,
  "category": <"Bug Fix" | "Feature" | "Refactor" | "Chore" | "Unclear">,
  "bug_type": <"Logic Error" | "UI Bug" | "Performance" | "Crash" | "Security" | "Data" | "Integration" | "Other" | "N/A">,
  "severity": <"Critical" | "Major" | "Minor" | "N/A">,
  "reasoning": "<1-2 sentence explanation>"
}

Rules:
- is_bug_fix=true when: commit message has fix/bug/hotfix/patch/resolve/แก้ keywords, OR diff adds null checks / error handling / corrects wrong logic
- is_bug_fix=false for: new features, refactors, dependency updates, docs, tests
- bug_type and severity must be "N/A" when is_bug_fix=false
- confidence=High when signal is clear, Medium when probable, Low when ambiguous
- Severity: Critical=crash/security/data-loss, Major=broken workflow, Minor=cosmetic/small

Example output:
{"is_bug_fix": true, "confidence": "High", "category": "Bug Fix", "bug_type": "Crash", "severity": "Critical", "reasoning": "Fixes null pointer when token is missing."}

/no_think
```

> `/no_think` ปิด thinking mode ของ Qwen 3 — ถ้าไม่มีจะช้ามากเพราะ model คิดก่อนตอบ

---

### System Prompt: Gemini

ระดับกลาง — ไม่ต้องบอก format JSON ใน prompt เพราะส่ง `response_schema` ไปบังคับ format โดยตรง

```
You are an expert software engineer specializing in code review and commit analysis.
Classify each Git commit as a bug fix or not, based on commit message and code diff.

Classification Rules:
- is_bug_fix=true: keywords fix/bug/hotfix/patch/resolve/regression/crash/revert; Thai: แก้/แก้ไข/ซ่อม
- is_bug_fix=true also when diff adds null checks, error handling, or corrects wrong logic
- is_bug_fix=false: new features, refactors, dependency updates, docs, tests, CI changes
- confidence: High=clear signal in both message+diff; Medium=probable but vague; Low=ambiguous
- severity (bugs only): Critical=crash/security/data-loss, Major=broken workflow, Minor=cosmetic
- bug_type and severity must be "N/A" when is_bug_fix=false

Provide 1-2 sentence reasoning.
```

นอกจาก prompt ยังส่ง `response_schema` แยกต่างหาก:

```python
response_schema = {
  "type": "object",
  "properties": {
    "is_bug_fix":   { "type": "boolean" },
    "confidence":   { "type": "string", "enum": ["High", "Medium", "Low"] },
    "category":     { "type": "string", "enum": ["Bug Fix", "Feature", "Refactor", "Chore", "Unclear"] },
    "bug_type":     { "type": "string", "enum": ["Logic Error", "UI Bug", "Performance", "Crash", "Security", "Data", "Integration", "Other", "N/A"] },
    "severity":     { "type": "string", "enum": ["Critical", "Major", "Minor", "N/A"] },
    "reasoning":    { "type": "string" }
  }
}
```

---

### System Prompt: Claude

ละเอียดที่สุด — ไม่ต้องบอก format เลยเพราะบังคับผ่าน tool schema แทน

```
You are an expert software engineer specializing in code review and commit analysis.
Your job is to classify each Git commit as a bug fix or not, based on the commit message and code diff provided.

## Classification Rules

**Bug Fix indicators (is_bug_fix = true):**
- Commit message contains: fix, bug, hotfix, patch, resolve, regression, issue, defect, error, crash, revert (if reverting a broken change)
- Thai keywords: แก้, แก้ไข, แก้บัค, แก้ปัญหา, ซ่อม
- Code changes show: added null/undefined checks, corrected logic conditions, fixed off-by-one errors, added missing error handling, corrected wrong variable usage

**NOT a bug fix:**
- New features, even if they handle edge cases (category = Feature)
- Code restructuring without behavior change (category = Refactor)
- Dependency updates, CI changes, docs (category = Chore)
- Ambiguous commits with no clear intent (category = Unclear, confidence = Low)

## Severity Guidelines (for bug fixes only)
- **Critical**: Data corruption, security vulnerability, system crash, data loss
- **Major**: Incorrect results, broken workflows, significant user impact
- **Minor**: UI glitch, cosmetic issue, minor logic error with limited impact

## Confidence Guidelines
- **High**: Clear fix keywords + diff shows defensive code / condition correction
- **Medium**: Probable fix but message is vague or diff is ambiguous
- **Low**: Cannot determine clearly, diff unavailable, or contradictory signals

Always provide reasoning in 1–2 concise sentences explaining your decision.
```

Claude บังคับ output ด้วย tool schema แทน JSON format ใน prompt:

```python
tool = {
  "name": "record_commit_analysis",
  "description": "Record the structured analysis of a Git commit.",
  "input_schema": {
    "type": "object",
    "properties": {
      "is_bug_fix":  { "type": "boolean" },
      "confidence":  { "type": "string", "enum": ["High", "Medium", "Low"] },
      "category":    { "type": "string", "enum": ["Bug Fix", "Feature", "Refactor", "Chore", "Unclear"] },
      ...
    }
  }
}
# บังคับให้ใช้ tool นี้ทุกครั้ง
tool_choice = {"type": "tool", "name": "record_commit_analysis"}
```

---

### เปรียบเทียบ 4 mode

| | Ollama | Gemini | OpenAI | Claude |
|---|---|---|---|---|
| บังคับ JSON ด้วย | `"format": "json"` | `response_schema` | `response_format` | `tool_use` |
| ความยาว System Prompt | สั้น | กลาง | กลาง | ยาว |
| มี example output | ✓ | ✗ | ✗ | ✗ |
| `/no_think` | ✓ | ✗ | ✗ | ✗ |
| ต้องบอก JSON schema ใน prompt | ✓ | ✗ | ✗ | ✗ |

---

### Step 3 — สร้าง Excel Report

**ไฟล์:** `excel_reporter.py`
**Output:** `output/bug_report_{sprint}_{timestamp}.xlsx`

สร้าง 3 sheets:

#### Sheet 1: Summary Dashboard

```
┌─────────────────────────────────────────────────────────┐
│  Sprint Bug Fix Analyzer — Sprint 1          [navy bar] │
│  Period: 2025-01-01 → 2025-01-14 | Generated: ...      │
├───────────┬───────────┬───────────┬─────────────────────┤
│  Total    │  Bug      │  Bug Fix  │  Non-Bug-Fix        │
│  Commits  │  Fixes    │  Rate     │  (Feat/Refac/Chore) │
│    87     │    23     │  26.4%    │        64           │  ← KPI Cards
├───────────┴───────────┴───────────┴─────────────────────┤
│ Sprint Overview    │ [Pie Chart: Bug Fix vs Non-Bug-Fix] │
│ Bug Fix by Dev     │                                     │
│ Category Breakdown │ [Bar Chart: Commits by Category]    │
│ Severity Breakdown │                                     │
│ Confidence Breakdown                                     │
└──────────────────────────────────────────────────────────┘
```

**Category Breakdown** แสดง description ของแต่ละ category:
| Category | Count | % | Description |
|---|---|---|---|
| Bug Fix | 23 | 26% | Fixes defects, crashes, or incorrect behavior... |
| Feature | 30 | 34% | Adds new functionality... |

**Confidence Breakdown** แสดงความน่าเชื่อถือของการวิเคราะห์:
| Confidence | Count | % of Bug Fixes |
|---|---|---|
| 🟢 High | 18 | 78% |
| 🟡 Medium | 4 | 17% |
| 🔴 Low | 1 | 4% |

#### Sheet 2: Commit Details

ทุก commit พร้อม color-coded rows ตาม category:
- 🔴 แดงอ่อน = Bug Fix
- 🟢 เขียวอ่อน = Feature
- 🔵 น้ำเงินอ่อน = Refactor
- 🟡 เหลืองอ่อน = Chore
- 🟣 ม่วงอ่อน = Unclear

มี **Auto-filter** ทุก column — กรองตาม author / severity / confidence ได้ทันที

Column สุดท้าย **"Keyword Signals / Reasoning"**:
- Keyword mode → บอกว่า match signal อะไร เช่น `conventional-commit fix prefix, null check in diff`
- AI mode → คำอธิบายจาก model เช่น `Fixes null pointer when token is missing.`

#### Sheet 3: Bug Fix Only

เหมือน Sheet 2 แต่กรองเฉพาะ Bug Fix commits + มี Sprint column สำหรับทำ Pivot Table ข้ามหลาย sprint

---

## Data Flow สรุป

```
.env
 │
 ├── Azure credentials  ──►  AzureDevOpsClient
 │                               │
 │                               ├── get_commits()        → list[CommitInfo (no diff)]
 │                               └── enrich_commits()     → list[CommitInfo (with diff)]
 │
 └── Analysis mode  ──► Analyzer (keyword/gemini/ollama/claude)
                             │
                             └── analyze_batch()  → list[CommitAnalysis]
                                      │
                                      └── excel_reporter.generate_report()
                                               │
                                               └── output/bug_report_*.xlsx
```

---

## ไฟล์ทั้งหมด

| ไฟล์ | หน้าที่ |
|---|---|
| `app.py` | FastAPI entry point — mount routers, serve static frontend |
| `sprint_bug_analyzer.py` | CLI Orchestrator — อ่าน .env, แสดง progress |
| `models.py` | Data classes: `SprintConfig`, `CommitInfo`, `CommitAnalysis` และ Enums |
| `azure_client.py` | ดึง commits, file list, unified diff จาก Azure DevOps REST API |
| `prompt.py` | Shared AI system prompt สำหรับทุก AI mode |
| `excel_reporter.py` | สร้าง Excel multi-sheet, KPI cards, charts, badges |
| `test_local.py` | ทดสอบด้วย 40 mock commits โดยไม่ต้องมี Azure |
| `.env.example` | Template config พร้อม comment อธิบายทุก variable |
| `analyzers/base.py` | BaseAnalyzer abstract class |
| `analyzers/keyword.py` | Regex-based classifier, 3 tier signals, ไม่ต้องใช้ API |
| `analyzers/gemini.py` | Google Gemini integration (AI Studio + Vertex AI) |
| `analyzers/openai.py` | OpenAI GPT integration |
| `analyzers/ollama.py` | Ollama local LLM integration, `/no_think` สำหรับ Qwen 3 |
| `analyzers/claude.py` | Anthropic Claude integration ด้วย forced tool-use |
| `routers/analyze.py` | GET /api/analyze — SSE streaming pipeline |
| `routers/config.py` | GET/POST/DELETE /api/config — in-memory config |
| `routers/azure.py` | GET /api/azure/* — projects/repos/branches/commit-dates |
| `routers/download.py` | GET /api/download/{filename} — Excel download |

---

## ทำไม Keyword mode ถึงไม่ดึง diff

การดึง diff ต้องเรียก Azure API **3 ครั้งต่อไฟล์**:
1. ดึง commit info → หา parent commit ID
2. ดึง file content ของ parent commit
3. ดึง file content ของ commit ปัจจุบัน

ถ้ามี 100 commits × 5 ไฟล์ = **1,500 API calls**

Keyword mode อ่านแค่ commit message + ชื่อไฟล์ก็พอ ดึงแค่ `/commits/{id}/changes` (1 call ต่อ commit) ประหยัดเวลาและ API quota
