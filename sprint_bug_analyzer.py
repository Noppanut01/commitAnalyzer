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
from claude_analyzer import ClaudeAnalyzer
from keyword_analyzer import KeywordAnalyzer
from ollama_analyzer import OllamaAnalyzer, OllamaError
from gemini_analyzer import GeminiAnalyzer, GeminiError
from excel_reporter import generate_report
from models import SprintConfig

VALID_MODES = ("claude", "gemini", "keyword", "ollama")

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
        print(f"ERROR: ANALYSIS_MODE must be one of {VALID_MODES}, got '{mode}'.")
        sys.exit(1)

    required = ALWAYS_REQUIRED.copy()
    if mode == "claude":
        required.append("ANTHROPIC_API_KEY")
    if mode == "gemini":
        use_vertex = os.getenv("GEMINI_USE_VERTEX", "false").strip().lower() == "true"
        if use_vertex:
            required.append("GOOGLE_CLOUD_PROJECT")
        else:
            required.append("GOOGLE_API_KEY")

    missing = [v for v in required if not os.getenv(v)]
    if missing:
        print("ERROR: The following environment variables are missing:")
        for var in missing:
            print(f"  • {var}")
        print("\nCopy .env.example → .env and fill in the values.")
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
    print("  Sprint Bug Fix Analyzer")
    print("=" * 60)

    config, mode = load_config()

    print(f"\nSprint : {config.sprint_name}")
    print(f"Range  : {config.sprint_start}  →  {config.sprint_end}")
    print(f"Repo   : {config.org}/{config.project}/{config.repo}")
    if config.branch:
        print(f"Branch : {config.branch}")
    _gemini_model = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
    _gemini_vertex = os.getenv("GEMINI_USE_VERTEX", "false").strip().lower() == "true"
    _gemini_backend = "Vertex AI" if _gemini_vertex else "AI Studio"
    mode_label = {
        "claude":   "Claude AI (cloud)",
        "gemini":   f"Google Gemini ({_gemini_model}) — {_gemini_backend}",
        "keyword":  "Keyword rules (no API key)",
        "ollama":   f"Ollama local — {os.getenv('OLLAMA_MODEL', 'qwen2.5:3b')}",
    }[mode]
    print(f"Mode   : {mode_label}")
    print()

    azure = AzureDevOpsClient(config)

    # ── Step 1: Fetch commits ────────────────────────────────────────────
    print("[1/3] Fetching commits from Azure DevOps...")
    try:
        commits = azure.get_commits()
    except AzureAPIError as exc:
        print(f"\nERROR: {exc}")
        sys.exit(1)

    if not commits:
        print("  No commits found in the given date range. Exiting.")
        sys.exit(0)

    print(f"  Found {len(commits)} commit(s).")

    # ── Step 1b: Fetch file list (+ diff for AI modes) ───────────────────
    needs_diff = mode in ("claude", "ollama", "gemini")
    fetch_label = "Fetching commit diffs..." if needs_diff else "Fetching file lists..."
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
    done_label = "diffs" if needs_diff else "file lists"
    _done_line(f"Fetched {done_label} for {len(commits)} commit(s).")

    # ── Step 2: Analyse commits ───────────────────────────────────────────
    if mode == "keyword":
        print(f"\n[2/3] Classifying with keyword rules ({len(commits)} total)...")
        analyzer = KeywordAnalyzer()

    elif mode == "ollama":
        ollama_model = os.getenv("OLLAMA_MODEL", "qwen2.5:3b").strip()
        ollama_url   = os.getenv("OLLAMA_URL", "http://localhost:11434").strip()
        print(f"\n[2/3] Analysing with Ollama ({ollama_model}) — {len(commits)} commits...")
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
        print(f"\n[2/3] Analysing with Gemini ({gemini_model}) via {backend_label} — {len(commits)} commits...")
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

    else:
        print(f"\n[2/3] Analysing with Claude ({len(commits)} total)...")
        analyzer = ClaudeAnalyzer(config.anthropic_api_key)

    try:
        analyses = analyzer.analyze_batch(
            commits,
            on_progress=lambda i, n, sha: _progress(i, n, sha),
        )
    except Exception as exc:
        print(f"\n\nERROR: {exc}")
        sys.exit(1)
    _done_line(f"Analysis complete for {len(analyses)} commit(s).")

    bug_count = sum(1 for a in analyses if a.is_bug_fix)
    fallback_count = sum(1 for a in analyses if a.is_fallback)
    bug_pct   = round(bug_count / len(analyses) * 100, 1) if analyses else 0
    print(f"  Bug fixes found: {bug_count} / {len(analyses)} ({bug_pct}%)")
    if fallback_count:
        print(f"  Warning: {fallback_count} commit(s) could not be analysed (fallback used).")

    # ── Step 3: Generate Excel report ────────────────────────────────────
    print(f"\n[3/3] Generating Excel report...")
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
    print(f"  Report saved: {filename}")
    print(f"  Sheets:")
    print(f"    • Summary Dashboard  — overview + charts")
    print(f"    • Commit Details     — all {len(analyses)} commit(s) colour-coded")
    print(f"    • Bug Fix Only       — {bug_count} bug fix commit(s)")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
