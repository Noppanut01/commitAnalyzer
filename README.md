# Sprint Bug Fix Analyzer

Fetches commits from Azure DevOps for a sprint, classifies each commit as a bug fix or not, and exports a formatted 3-sheet Excel report with charts.

Supports two interfaces:
- **Web UI** — React + FastAPI (recommended)
- **CLI** — terminal-only, reads config from `.env`

Supports four analysis modes:

| Mode | Description | Cost |
|---|---|---|
| `claude` | Claude AI via Anthropic API — best accuracy | ~$0.003/commit |
| `gemini` | Google Gemini via AI Studio or Vertex AI | ~$0.001/commit |
| `ollama` | Local LLM via Ollama — no internet required | Free |
| `keyword` | Regex keyword rules — instant, no model needed | Free |

---

## Requirements

- Python 3.11+
- Azure DevOps Personal Access Token (Code Read permission)
- API key depending on mode (see Configuration)

## Installation

```bash
pip install -r requirements.txt
```

---

## Running — Web UI (recommended)

The web UI lets you fill in all settings through a browser form with no `.env` required. Credentials are stored in RAM only and cleared when the server stops.

**Development** (hot-reload on both backend and frontend):

```bash
# Terminal 1 — backend
uvicorn app:app --reload

# Terminal 2 — frontend
cd frontend
npm install
npm run dev
```

Open [http://localhost:5173](http://localhost:5173)

**Production** (serve frontend as static files from the backend):

```bash
cd frontend && npm run build && cd ..
uvicorn app:app --host 0.0.0.0 --port 8000
```

Open [http://localhost:8000](http://localhost:8000)

---

## Running — CLI

### Configuration

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

#### Azure DevOps (required for all modes)

| Variable | Description |
|---|---|
| `AZURE_ORG` | Azure DevOps organization name |
| `AZURE_PROJECT` | Project name |
| `AZURE_REPO` | Repository name |
| `AZURE_PAT` | Personal Access Token (Code Read scope) |
| `AZURE_BRANCH` | *(optional)* Filter commits by branch |
| `SPRINT_START` | Sprint start date `YYYY-MM-DD` |
| `SPRINT_END` | Sprint end date `YYYY-MM-DD` |
| `SPRINT_NAME` | Sprint label used in the report |

#### Analysis mode

Set `ANALYSIS_MODE` to one of: `claude`, `gemini`, `ollama`, `keyword`

**Claude mode**
```env
ANALYSIS_MODE=claude
ANTHROPIC_API_KEY=sk-ant-...
```

**Gemini mode — Option A: Google AI Studio** (free quota + pay-per-token)
```env
ANALYSIS_MODE=gemini
GOOGLE_API_KEY=AIzaSy...        # from aistudio.google.com/apikey
GEMINI_MODEL=gemini-2.0-flash   # or gemini-1.5-flash, gemini-1.5-pro
```

**Gemini mode — Option B: Vertex AI** (Google Cloud credits)
```env
ANALYSIS_MODE=gemini
GEMINI_USE_VERTEX=true
GOOGLE_CLOUD_PROJECT=my-gcp-project
GOOGLE_CLOUD_REGION=us-central1
GEMINI_MODEL=gemini-2.0-flash
```
Authenticate first: `gcloud auth application-default login`

**Ollama mode** (local LLM — Qwen 2.5 or Qwen 3 recommended)
```env
ANALYSIS_MODE=ollama
OLLAMA_MODEL=qwen2.5:3b    # qwen2.5:3b (8 GB RAM) | qwen2.5:7b (16 GB+)
OLLAMA_URL=http://localhost:11434
```
> Qwen 3 models have a thinking mode that is slow. The tool automatically disables it via `/no_think` in the system prompt.

**Keyword mode** (no API key)
```env
ANALYSIS_MODE=keyword
```

### Usage

```bash
python sprint_bug_analyzer.py
```

```
============================================================
  Sprint Bug Fix Analyzer
============================================================

Sprint : Sprint 42
Range  : 2025-01-06  →  2025-01-17
Repo   : my-org/my-project/my-repo
Mode   : Claude AI (cloud)

[1/3] Fetching commits from Azure DevOps...
  Found 87 commit(s).
  Fetching commit diffs...
  [==============================]   87/87  abc1234

[2/3] Analysing with Claude (87 total)...
  [==============================]   87/87  def5678
  Bug fixes found: 23 / 87 (26.4%)

[3/3] Generating Excel report...

============================================================
  Report saved: bug_report_Sprint_42_20250117_1430.xlsx
  Sheets:
    • Summary Dashboard  — overview + charts
    • Commit Details     — all 87 commit(s) colour-coded
    • Bug Fix Only       — 23 bug fix commit(s)
============================================================
```

---

## Local Testing (no Azure DevOps required)

Use the included test script with 40 mock commits to verify the tool and try different modes without any Azure credentials:

```bash
python test_local.py                              # keyword mode (default)
python test_local.py --mode keyword
python test_local.py --mode ollama --model qwen2.5:3b
python test_local.py --mode ollama --model qwen3:latest
python test_local.py --mode claude --key sk-ant-...
python test_local.py --mode gemini --key AIzaSy...
python test_local.py --mode gemini --vertex --project my-gcp-project
```

---

## Excel Report

### Sheet 1 — Summary Dashboard

- **4 KPI cards**: Total Commits · Bug Fixes · Bug Fix Rate · Non-Bug-Fix count
- **Sprint Overview**: sprint name, date range, totals
- **Bug Fix by Developer**: sorted by bug fix count
- **Category Breakdown**: count + % + description of each category
- **Severity Breakdown**: Critical / Major / Minor counts for bug fixes
- **Confidence Breakdown**: High / Medium / Low confidence counts for bug fixes
- **Pie chart**: Bug Fix vs Non-Bug-Fix
- **Bar chart**: Commits by category

#### Category descriptions

| Category | Meaning |
|---|---|
| Bug Fix | Fixes defects, crashes, or incorrect behavior in existing code |
| Feature | Adds new functionality or capabilities to the system |
| Refactor | Restructures code without changing external behavior |
| Chore | CI config, dependencies, docs, tests, version bumps |
| Unclear | Cannot determine intent — message too vague or ambiguous |

#### Confidence levels (bug fixes)

| Confidence | Meaning |
|---|---|
| High | Clear signal — fix keyword + matching diff pattern |
| Medium | Probable fix — message or diff has some ambiguity |
| Low | Weak signal — diff pattern only, no fix keyword |

### Sheet 2 — Commit Details

All commits with colour-coded rows by category and badge cells for severity/confidence.

| Column | Description |
|---|---|
| # | Row number |
| Date | Commit date |
| Commit ID | Short hash (7 chars) |
| Author | Commit author |
| Message | Full commit message |
| Bug Fix | Yes / No badge |
| Category | Bug Fix / Feature / Refactor / Chore / Unclear |
| Bug Type | Logic Error / UI Bug / Performance / Crash / Security / Data / Integration |
| Severity | Critical / Major / Minor badge |
| Confidence | High / Medium / Low badge |
| Files Changed | List of changed file paths |
| Keyword Signals / Reasoning | Keywords matched or AI explanation |

Auto-filter is enabled on all columns.

### Sheet 3 — Bug Fix Only

Same as Sheet 2, filtered to bug fix commits only. Includes a Sprint column for pivot table use.

---

## File Structure

```
commitAnalyzer/
├── app.py                   # FastAPI backend + SSE analysis endpoint
├── sprint_bug_analyzer.py   # CLI entry point
├── models.py                # Dataclasses and enums
├── azure_client.py          # Azure DevOps REST API client
├── prompt.py                # Shared AI system prompt (Claude / Gemini / Ollama)
├── claude_analyzer.py       # Claude AI integration (tool-use)
├── gemini_analyzer.py       # Google Gemini integration (AI Studio + Vertex AI)
├── ollama_analyzer.py       # Ollama local LLM integration
├── keyword_analyzer.py      # Regex keyword rule-based classifier
├── excel_reporter.py        # Excel report generation (3 sheets + charts)
├── test_local.py            # Local test runner with 40 mock commits
├── requirements.txt
├── .env.example
└── frontend/                # React + Vite web UI
    ├── src/
    │   ├── pages/
    │   │   ├── ConfigPage.jsx
    │   │   └── ReportPage.jsx
    │   └── components/
    │       ├── KpiCards.jsx
    │       ├── DevTable.jsx
    │       ├── CategoryTable.jsx
    │       ├── CommitTable.jsx
    │       └── ModeFields.jsx
    ├── package.json
    └── vite.config.js
```

---

## How commits are classified

All AI modes (Claude, Gemini, Ollama) analyse the commit message and code diff together to produce structured output.

**Bug fix signals:**
- Keywords: `fix`, `bug`, `hotfix`, `patch`, `resolve`, `regression`, `crash`, `revert`
- Thai keywords: `แก้`, `แก้ไข`, `แก้บัค`, `แก้ปัญหา`, `ซ่อม`
- AI-style verbs paired with a problem noun: `resolve X failure`, `prevent crash when`, `address memory leak`
- Technical bug terms: `race condition`, `null pointer`, `off-by-one`, `deadlock`, `memory leak`
- Code diff patterns: added null checks, added try/catch blocks, corrected logic conditions

**Severity assessment (bug fixes only):**
- **Critical** — data corruption, security vulnerability, system crash, infinite loop
- **Major** — incorrect results, broken workflows, race condition, memory leak
- **Minor** — UI glitch, cosmetic issue, limited-impact logic error

---

## Error Handling

| Situation | Behaviour |
|---|---|
| Azure 401 | Exits with "check your PAT" message |
| Azure 404 | Exits with "verify org/project/repo" message |
| Azure 429 / 503 | Retries 3× with 2s → 4s → 8s backoff |
| Binary file diff | Records `[Binary file]` in diff |
| AI tool-use missing | Fallback sentinel recorded, batch continues |
| Claude / Gemini 429 | Sleeps and retries up to 2× |
| Invalid API key | Exits immediately with clear message |
| Ollama not running | Exits with `ollama serve` instructions |
| Ollama model not pulled | Exits with `ollama pull <model>` instructions |
| Excel file locked | Exits with "close Excel first" message |

---

## Limitations

- Large commits are truncated to 8 000 characters of diff and 10 files before being sent to AI (to control token cost).
- AI accuracy depends on commit message quality. Vague messages receive `Confidence = Low`.
- Keyword mode does not read diff — diff fetching is skipped when `ANALYSIS_MODE=keyword` to save time.
