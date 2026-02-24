# Sprint Bug Fix Analyzer

Fetches commits from Azure DevOps for a sprint, classifies each commit as a bug fix or not, and exports a formatted Excel report with charts.

Supports two interfaces:
- **Web UI** — React + FastAPI (recommended)
- **CLI** — terminal-only, reads config from `.env`

Supports five analysis modes:

| Mode | Description | Cost |
|---|---|---|
| `claude` | Claude AI via Anthropic API — best accuracy | ~$0.003/commit |
| `gemini` | Google Gemini via AI Studio or Vertex AI | ~$0.001/commit |
| `openai` | OpenAI GPT via OpenAI API | ~$0.002/commit |
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

Set `ANALYSIS_MODE` to one of: `claude`, `gemini`, `openai`, `ollama`, `keyword`

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

**OpenAI mode**
```env
ANALYSIS_MODE=openai
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o-mini    # or gpt-4o, gpt-4-turbo
```

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
python test_local.py --mode openai --key sk-...
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

All commits with colour-coded rows by category and badge cells for Bug Fix / Severity.

| Column | Description |
|---|---|
| Date | Commit date |
| Commit ID | Short hash (7 chars), hyperlinks to PR sheet for merge commits |
| Message | Commit message (truncated to 2 lines) |
| Author | Commit author |
| Bug Fix | Yes / No badge |
| Category | Bug Fix / Feature / Refactor / Chore / Unclear |
| Severity | Critical / Major / Minor / N/A badge |
| Reasoning | Keywords matched (keyword mode) or AI explanation |

Merge commits are expandable — click the hyperlinked Commit ID to open the PR detail sheet.
Auto-filter is enabled on all columns.

### Sheet 3 — Bug Fix Only

Same as Sheet 2, filtered to bug fix commits only.

### PR Detail Sheets

One sheet per merge commit, listing all individual commits inside that PR.

---

## File Structure

```
bugAnalyzer/
├── app.py                    # FastAPI entry point — mounts routers, serves static frontend
├── sprint_bug_analyzer.py    # CLI entry point
├── models.py                 # Dataclasses and enums (CommitInfo, CommitAnalysis, etc.)
├── azure_client.py           # Azure DevOps REST API client
├── prompt.py                 # Shared AI system prompt (Claude / Gemini / OpenAI / Ollama)
├── excel_reporter.py         # Excel report generation (multi-sheet + charts)
├── test_local.py             # Local test runner with 40 mock commits
├── requirements.txt
├── .env.example
├── analyzers/
│   ├── base.py               # BaseAnalyzer abstract class
│   ├── claude.py             # Claude AI integration (forced tool-use)
│   ├── gemini.py             # Google Gemini (AI Studio + Vertex AI)
│   ├── openai.py             # OpenAI GPT integration
│   ├── ollama.py             # Ollama local LLM integration
│   └── keyword.py            # Regex keyword rule-based classifier
├── routers/
│   ├── analyze.py            # GET /api/analyze — SSE streaming analysis pipeline
│   ├── config.py             # GET/POST/DELETE /api/config — in-memory config store
│   ├── azure.py              # GET /api/azure/* — projects / repos / branches / commit-dates
│   └── download.py           # GET /api/download/{filename} — Excel file download
└── frontend/                 # React + Vite web UI
    ├── src/
    │   ├── App.jsx
    │   ├── main.jsx
    │   ├── styles.css
    │   ├── pages/
    │   │   ├── ConfigPage.jsx
    │   │   └── ReportPage.jsx
    │   └── components/
    │       ├── CommitTable.jsx
    │       ├── KpiCards.jsx
    │       ├── DevTable.jsx
    │       ├── CategoryTable.jsx
    │       └── ModeFields.jsx
    ├── package.json
    └── vite.config.js
```

---

## How commits are classified

All AI modes (Claude, Gemini, OpenAI, Ollama) analyse the commit message and code diff together to produce structured output.

**Bug fix signals (keyword mode — 3 tiers):**

| Tier | Signal | Example |
|---|---|---|
| HIGH | Conventional commit fix prefix | `fix:` `hotfix(scope):` `patch:` `revert:` |
| HIGH | Issue reference | `fixes #123` `closes #456` |
| HIGH | Technical bug terms | `null pointer` `race condition` `segfault` `OOM` `deadlock` `assertion fail` |
| MEDIUM | Bug/fix keywords | `fix` `bug` `broken` `typo` `glitch` `regression` `rollback` |
| MEDIUM | AI-style verb + problem | `resolve X failure` `prevent crash` `sanitize input` `validate param` |
| MEDIUM | Edge case language | `edge case` `corner case` `boundary condition` `concurrent access` |
| LOW | Diff patterns only | null check added, try/catch added |

**Severity assessment (bug fixes only):**
- **Critical** — data corruption, security vulnerability, system crash, production outage, OOM
- **Major** — incorrect results, broken workflows, regression, race condition, memory leak
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
