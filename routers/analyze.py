"""
SSE analysis endpoint and pipeline orchestration.

Endpoint:
    GET /api/analyze  — Server-Sent Events stream that runs the full pipeline:
                        fetch → enrich → analyze → Excel report → result JSON
"""

import asyncio
import json
import os
import queue
from collections import Counter
from datetime import datetime

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from analyzers import (
    ClaudeAnalysisError,
    GeminiError,
    OllamaError,
    get_analyzer,
)
from azure_client import AzureAPIError, AzureDevOpsClient
from excel_reporter import generate_report
from models import CommitInfo, SprintConfig
from routers.config import _config

router = APIRouter()


# ---------------------------------------------------------------------------
# Result builder
# ---------------------------------------------------------------------------


def _build_result(commits: list[CommitInfo], analyses, filename: str) -> dict:
    commit_map = {c.commit_id: c for c in commits}
    total      = len(analyses)
    bug_count  = sum(1 for a in analyses if a.is_bug_fix)

    dev_bug:   Counter = Counter()
    dev_total: Counter = Counter()
    for a in analyses:
        author = commit_map.get(a.commit_id, CommitInfo("", "Unknown", "", "", "")).author
        dev_total[author] += 1
        if a.is_bug_fix:
            dev_bug[author] += 1

    dev_table = [
        {
            "developer": dev,
            "total":     dev_total[dev],
            "bug_fixes": dev_bug.get(dev, 0),
            "pct":       round(dev_bug.get(dev, 0) / dev_total[dev] * 100, 1),
        }
        for dev in sorted(dev_total, key=lambda d: (-dev_bug.get(d, 0), d))
    ]

    cat_counter: Counter = Counter(a.category.value for a in analyses)
    cat_table = [
        {
            "category": cat,
            "count":    cat_counter.get(cat, 0),
            "pct":      round(cat_counter.get(cat, 0) / total * 100, 1) if total else 0,
        }
        for cat in ["Bug Fix", "Feature", "Refactor", "Chore", "Unclear"]
    ]

    commit_rows = [
        {
            "commit_id":     a.commit_id[:7],
            "date":          (commit_map[a.commit_id].date[:10] if a.commit_id in commit_map else ""),
            "author":        (commit_map[a.commit_id].author if a.commit_id in commit_map else ""),
            "message":       (commit_map[a.commit_id].message if a.commit_id in commit_map else ""),
            "is_bug_fix":    a.is_bug_fix,
            "category":      a.category.value,
            "bug_type":      a.bug_type.value,
            "severity":      a.severity.value,
            "confidence":    a.confidence.value,
            "files_changed": a.files_changed[:10],
            "reasoning":     a.reasoning,
        }
        for a in analyses
    ]

    return {
        "kpis": {
            "total_commits": total,
            "bug_fixes":     bug_count,
            "bug_fix_rate":  round(bug_count / total * 100, 1) if total else 0,
            "non_bug_fix":   total - bug_count,
        },
        "dev_table":   dev_table,
        "cat_table":   cat_table,
        "commit_rows": commit_rows,
        "filename":    filename,
    }


# ---------------------------------------------------------------------------
# Pipeline (runs in a thread-pool worker)
# ---------------------------------------------------------------------------


def _run_pipeline(q: queue.Queue) -> None:
    try:
        cfg  = dict(_config)   # snapshot of in-memory config
        mode = (cfg.get("analysis_mode") or "claude").strip().lower()

        config = SprintConfig(
            org=(cfg.get("azure_org") or "").strip(),
            project=(cfg.get("azure_project") or "").strip(),
            repo=(cfg.get("azure_repo") or "").strip(),
            pat=(cfg.get("azure_pat") or "").strip(),
            anthropic_api_key=(cfg.get("anthropic_api_key") or "").strip(),
            sprint_start=(cfg.get("sprint_start") or "").strip(),
            sprint_end=(cfg.get("sprint_end") or "").strip(),
            sprint_name=(cfg.get("sprint_name") or "").strip(),
            branch=(cfg.get("azure_branch") or "").strip(),
        )

        # ── Step 1: Fetch commits ────────────────────────────────────────
        q.put({"type": "status", "phase": "fetch",
               "message": "กำลังดึง commits จาก Azure DevOps..."})

        azure   = AzureDevOpsClient(config)
        commits = azure.get_commits()

        if not commits:
            q.put({"type": "error", "message": "ไม่พบ commit ในช่วงเวลาที่กำหนด"})
            return

        # ── Step 1b: Enrich (diff / file list) ──────────────────────────
        needs_diff = mode in ("claude", "ollama", "gemini")
        q.put({"type": "progress", "phase": "enrich",
               "current": 0, "total": len(commits),
               "message": f"พบ {len(commits)} commit — กำลังดึง{'diff' if needs_diff else 'รายชื่อไฟล์'}..."})

        def on_enrich(i, n, sha):
            q.put({"type": "progress", "phase": "enrich",
                   "current": i, "total": n, "sha": sha,
                   "message": f"ดึงข้อมูล {i}/{n}: {sha}"})

        commits = azure.enrich_commits(
            commits, on_progress=on_enrich, fetch_diff=needs_diff
        )

        # ── Step 2: Analyse ──────────────────────────────────────────────
        q.put({"type": "status", "phase": "analyze",
               "message": f"กำลังวิเคราะห์ {len(commits)} commit ด้วย {mode}..."})

        analyzer = get_analyzer(mode, cfg)   # may raise OllamaError / GeminiError

        def on_analyze(i, n, sha):
            q.put({"type": "progress", "phase": "analyze",
                   "current": i, "total": n, "sha": sha,
                   "message": f"วิเคราะห์ {i}/{n}: {sha}"})

        analyses = analyzer.analyze_batch(commits, on_progress=on_analyze)

        # ── Step 3: Generate Excel ───────────────────────────────────────
        q.put({"type": "status", "phase": "report",
               "message": "กำลังสร้างรายงาน Excel..."})

        safe_sprint = config.sprint_name.replace(" ", "_").replace("/", "-")
        timestamp   = datetime.now().strftime("%Y%m%d_%H%M")
        os.makedirs("output", exist_ok=True)
        filename    = f"bug_report_{safe_sprint}_{timestamp}.xlsx"
        filepath    = os.path.join("output", filename)

        generate_report(
            commits=commits,
            analyses=analyses,
            sprint_name=config.sprint_name,
            sprint_start=config.sprint_start,
            sprint_end=config.sprint_end,
            filepath=filepath,
        )

        q.put({"type": "complete", "data": _build_result(commits, analyses, filename)})

    except (AzureAPIError, ClaudeAnalysisError, GeminiError, OllamaError) as exc:
        q.put({"type": "error", "message": str(exc)})
    except Exception as exc:
        q.put({"type": "error", "message": f"ข้อผิดพลาด: {exc}"})
    finally:
        q.put(None)   # sentinel — signals the event stream to close


# ---------------------------------------------------------------------------
# SSE endpoint
# ---------------------------------------------------------------------------


@router.get("/api/analyze")
async def analyze():
    q: queue.Queue = queue.Queue()

    async def event_stream():
        loop   = asyncio.get_event_loop()
        thread = loop.run_in_executor(None, lambda: _run_pipeline(q))

        while True:
            try:
                event = await loop.run_in_executor(
                    None, lambda: q.get(timeout=0.1)
                )
            except queue.Empty:
                yield 'data: {"type":"heartbeat"}\n\n'
                continue

            if event is None:
                break

            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

        await thread

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
