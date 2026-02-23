#!/usr/bin/env python3
"""
Sprint Bug Fix Analyzer
=======================
Fetch commits from Azure DevOps, classify each with Claude,
and export a 3-sheet Excel report.

Usage:
    1. Copy .env.example → .env and fill in your credentials.
    2. pip install -r requirements.txt
    3. python sprint_bug_analyzer.py
"""

import os
import sys
from datetime import datetime

from dotenv import load_dotenv

from azure_client import AzureAPIError, AzureDevOpsClient
from analyzers import (
    ClaudeAnalyzer,
    GeminiAnalyzer,
    GeminiError,
    KeywordAnalyzer,
    OllamaAnalyzer,
    OllamaError,
    OpenAIAnalyzer,
    OpenAIError,
)
from excel_reporter import generate_report
from models import SprintConfig

VALID_MODES = ("claude", "gemini", "keyword", "ollama", "openai")

# ---------------------------------------------------------------------------
# Configuration loader
# ---------------------------------------------------------------------------

ALWAYS_REQUIRED = [
    "AZURE_ORG",
    "AZURE_PROJECT",
    "AZURE_REPO",
    "AZURE_PAT",
    "SPRINT_START",
    "SPRINT_END",
    "SPRINT_NAME",
]


def load_config() -> tuple[SprintConfig, str]:
    """Returns (SprintConfig, analysis_mode)."""
    load_dotenv()

    mode = os.getenv("ANALYSIS_MODE", "claude").strip().lower()
    if mode not in VALID_MODES:
        print(f"ข้อผิดพลาด: ANALYSIS_MODE ต้องเป็นหนึ่งใน {VALID_MODES} แต่ได้รับ '{mode}'")
        sys.exit(1)

    required = ALWAYS_REQUIRED.copy()
    if mode == "claude":
        required.append("ANTHROPIC_API_KEY")
    if mode == "openai":
        required.append("OPENAI_API_KEY")
    if mode == "gemini":
        use_vertex = os.getenv("GEMINI_USE_VERTEX", "false").strip().lower() == "true"
        if use_vertex:
            required.append("GOOGLE_CLOUD_PROJECT")
        else:
            required.append("GOOGLE_API_KEY")

    missing = [v for v in required if not os.getenv(v)]
    if missing:
        print("ข้อผิดพลาด: ตัวแปร environment ต่อไปนี้ยังไม่ได้ตั้งค่า:")
        for var in missing:
            print(f"  • {var}")
        print("\nคัดลอก .env.example → .env และกรอกค่าให้ครบ")
        sys.exit(1)

    config = SprintConfig(
        org=os.environ["AZURE_ORG"].strip(),
        project=os.environ["AZURE_PROJECT"].strip(),
        repo=os.environ["AZURE_REPO"].strip(),
        pat=os.environ["AZURE_PAT"].strip(),
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", "").strip(),
        sprint_start=os.environ["SPRINT_START"].strip(),
        sprint_end=os.environ["SPRINT_END"].strip(),
        sprint_name=os.environ["SPRINT_NAME"].strip(),
        branch=os.getenv("AZURE_BRANCH", "").strip(),
    )
    return config, mode


# ---------------------------------------------------------------------------
# Progress bar
# ---------------------------------------------------------------------------

BAR_WIDTH = 30


def _progress(current: int, total: int, label: str = "") -> None:
    filled  = int(BAR_WIDTH * current / total) if total else BAR_WIDTH
    bar     = "=" * filled + "-" * (BAR_WIDTH - filled)
    label   = label[:12].ljust(12)
    print(f"\r  [{bar}] {current:>4}/{total}  {label}", end="", flush=True)


def _done_line(msg: str) -> None:
    print(f"\r  {msg}" + " " * (BAR_WIDTH + 30))


# ---------------------------------------------------------------------------
# Main orchestration
# ---------------------------------------------------------------------------

def main() -> None:
    print("=" * 60)
    print("  วิเคราะห์ Bug Fix ใน Sprint")
    print("=" * 60)

    config, mode = load_config()

    print(f"\nSprint    : {config.sprint_name}")
    print(f"ช่วงเวลา  : {config.sprint_start}  →  {config.sprint_end}")
    print(f"Repository: {config.org}/{config.project}/{config.repo}")
    if config.branch:
        print(f"Branch    : {config.branch}")
    _gemini_model = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
    _gemini_vertex = os.getenv("GEMINI_USE_VERTEX", "false").strip().lower() == "true"
    _gemini_backend = "Vertex AI" if _gemini_vertex else "AI Studio"
    _openai_model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    mode_label = {
        "claude":   "Claude AI (cloud)",
        "gemini":   f"Google Gemini ({_gemini_model}) — {_gemini_backend}",
        "keyword":  "Keyword rules (ไม่ต้อง API key)",
        "ollama":   f"Ollama local — {os.getenv('OLLAMA_MODEL', 'qwen2.5:3b')}",
        "openai":   f"OpenAI ({_openai_model})",
    }[mode]
    print(f"โหมด      : {mode_label}")
    print()

    azure = AzureDevOpsClient(config)

    # ── Step 1: Fetch commits ────────────────────────────────────────────
    print("[1/3] กำลังดึง commits จาก Azure DevOps...")
    try:
        commits = azure.get_commits()
    except AzureAPIError as exc:
        print(f"\nERROR: {exc}")
        sys.exit(1)

    if not commits:
        print("  ไม่พบ commit ในช่วงเวลาที่กำหนด")
        sys.exit(0)

    print(f"  พบ {len(commits)} commit")

    # ── Step 1b: Fetch file list (+ diff for AI modes) ───────────────────
    needs_diff = mode in ("claude", "ollama", "gemini", "openai")
    fetch_label = "กำลังดึง diff..." if needs_diff else "กำลังดึงรายชื่อไฟล์..."
    print(f"  {fetch_label}", flush=True)
    try:
        commits = azure.enrich_commits(
            commits,
            on_progress=lambda i, n, sha: _progress(i, n, sha),
            fetch_diff=needs_diff,
        )
    except AzureAPIError as exc:
        print(f"\nERROR: {exc}")
        sys.exit(1)
    done_label = "diff" if needs_diff else "รายชื่อไฟล์"
    _done_line(f"ดึงข้อมูล {done_label} ครบ {len(commits)} commit")

    # ── Step 2: Analyse commits ───────────────────────────────────────────
    if mode == "keyword":
        print(f"\n[2/3] กำลังจำแนกด้วย keyword rules ({len(commits)} commit)...")
        analyzer = KeywordAnalyzer()

    elif mode == "ollama":
        ollama_model = os.getenv("OLLAMA_MODEL", "qwen2.5:3b").strip()
        ollama_url   = os.getenv("OLLAMA_URL", "http://localhost:11434").strip()
        print(f"\n[2/3] กำลังวิเคราะห์ด้วย Ollama ({ollama_model}) — {len(commits)} commit...")
        try:
            analyzer = OllamaAnalyzer(model=ollama_model, base_url=ollama_url)
        except OllamaError as exc:
            print(f"\nERROR: {exc}")
            sys.exit(1)

    elif mode == "gemini":
        gemini_model  = os.getenv("GEMINI_MODEL", "gemini-2.0-flash").strip()
        use_vertex    = os.getenv("GEMINI_USE_VERTEX", "false").strip().lower() == "true"
        gcp_project   = os.getenv("GOOGLE_CLOUD_PROJECT", "").strip()
        gcp_region    = os.getenv("GOOGLE_CLOUD_REGION", "us-central1").strip()
        google_api_key = os.getenv("GOOGLE_API_KEY", "").strip()
        backend_label = f"Vertex AI ({gcp_project})" if use_vertex else "AI Studio"
        print(f"\n[2/3] กำลังวิเคราะห์ด้วย Gemini ({gemini_model}) ผ่าน {backend_label} — {len(commits)} commit...")
        try:
            analyzer = GeminiAnalyzer(
                api_key=google_api_key,
                project=gcp_project,
                region=gcp_region,
                use_vertex=use_vertex,
                model=gemini_model,
            )
        except GeminiError as exc:
            print(f"\nERROR: {exc}")
            sys.exit(1)

    elif mode == "openai":
        openai_model = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip()
        openai_key   = os.getenv("OPENAI_API_KEY", "").strip()
        print(f"\n[2/3] กำลังวิเคราะห์ด้วย OpenAI ({openai_model}) — {len(commits)} commit...")
        try:
            analyzer = OpenAIAnalyzer(api_key=openai_key, model=openai_model)
        except OpenAIError as exc:
            print(f"\nERROR: {exc}")
            sys.exit(1)

    else:
        print(f"\n[2/3] กำลังวิเคราะห์ด้วย Claude ({len(commits)} commit)...")
        analyzer = ClaudeAnalyzer(config.anthropic_api_key)

    try:
        analyses = analyzer.analyze_batch(
            commits,
            on_progress=lambda i, n, sha: _progress(i, n, sha),
        )
    except Exception as exc:
        print(f"\n\nERROR: {exc}")
        sys.exit(1)
    _done_line(f"วิเคราะห์ {len(analyses)} commit เรียบร้อย")

    bug_count = sum(1 for a in analyses if a.is_bug_fix)
    fallback_count = sum(1 for a in analyses if a.is_fallback)
    bug_pct   = round(bug_count / len(analyses) * 100, 1) if analyses else 0
    print(f"  พบ Bug Fix: {bug_count} / {len(analyses)} ({bug_pct}%)")
    if fallback_count:
        print(f"  คำเตือน: {fallback_count} commit วิเคราะห์ไม่สำเร็จ (ใช้ค่าสำรอง)")

    # ── Step 3: Generate Excel report ────────────────────────────────────
    print(f"\n[3/3] กำลังสร้างรายงาน Excel...")
    safe_sprint = config.sprint_name.replace(" ", "_").replace("/", "-")
    timestamp   = datetime.now().strftime("%Y%m%d_%H%M")
    os.makedirs("output", exist_ok=True)
    filename    = os.path.join("output", f"bug_report_{safe_sprint}_{timestamp}.xlsx")

    try:
        generate_report(
            commits=commits,
            analyses=analyses,
            sprint_name=config.sprint_name,
            sprint_start=config.sprint_start,
            sprint_end=config.sprint_end,
            filepath=filename,
        )
    except PermissionError as exc:
        print(f"\nERROR: {exc}")
        sys.exit(1)

    print(f"\n{'=' * 60}")
    print(f"  บันทึกรายงาน: {filename}")
    print(f"  Sheets:")
    print(f"    • แดชบอร์ดสรุป      — ภาพรวม + กราฟ")
    print(f"    • รายละเอียด Commit  — ทั้งหมด {len(analyses)} commit")
    print(f"    • เฉพาะ Bug Fix      — {bug_count} commit")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
