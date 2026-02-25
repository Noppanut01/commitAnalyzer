#!/usr/bin/env python3
"""
Local test runner — no Azure DevOps required.

Creates a set of mock commits that cover:
  - Human-style bug fixes          (fix, แก้, patch, ...)
  - AI-style bug fixes             (resolve X failure, prevent null pointer, ...)
  - AI technical term bug fixes    (race condition, memory leak, off-by-one, ...)
  - Features                       (feat:, เพิ่ม, ...)
  - Refactors / Chores
  - Ambiguous / Unclear commits
  - Diff-only signals              (null check / try-catch added, no fix keyword)

Usage:
    python3 test_local.py                          # keyword mode (default)
    python3 test_local.py --mode keyword
    python3 test_local.py --mode ollama
    python3 test_local.py --mode ollama --model qwen2.5:7b
"""

import argparse
import hashlib
import sys
from datetime import datetime, timedelta

from excel_reporter import generate_report
from analyzers import KeywordAnalyzer
from models import CommitInfo

# ---------------------------------------------------------------------------
# Mock commit factory
# ---------------------------------------------------------------------------

def _sha(seed: str) -> str:
    return hashlib.sha1(seed.encode()).hexdigest()


def _date(days_ago: int) -> str:
    dt = datetime(2025, 1, 17) - timedelta(days=days_ago)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _commit(message: str, author: str, files: list[str],
            diff: str = "", days_ago: int = 0) -> CommitInfo:
    return CommitInfo(
        commit_id=_sha(message + author),
        author=author,
        author_email=author.lower().replace(" ", ".") + "@company.com",
        date=_date(days_ago),
        message=message,
        files_changed=files,
        diff_text=diff,
    )


# ---------------------------------------------------------------------------
# Diff snippets
# ---------------------------------------------------------------------------

DIFF_NULL_CHECK = """\
--- a/src/auth/token.py
+++ b/src/auth/token.py
@@ -12,6 +12,9 @@ def get_user(token):
     payload = decode(token)
+    if payload is None:
+        raise ValueError("Invalid token")
     return payload["user_id"]
"""

DIFF_TRY_CATCH = """\
--- a/src/payment/processor.py
+++ b/src/payment/processor.py
@@ -45,6 +45,10 @@ def charge(amount):
-    result = gateway.charge(amount)
+    try:
+        result = gateway.charge(amount)
+    except GatewayError as e:
+        logger.error(f"Charge failed: {e}")
+        raise
     return result
"""

DIFF_FEATURE = """\
--- /dev/null
+++ b/src/features/export.py
@@ -0,0 +1,20 @@
+def export_csv(data):
+    \"\"\"Export data to CSV format.\"\"\"
+    import csv, io
+    output = io.StringIO()
+    writer = csv.writer(output)
+    for row in data:
+        writer.writerow(row)
+    return output.getvalue()
"""

DIFF_REFACTOR = """\
--- a/src/utils/helpers.py
+++ b/src/utils/helpers.py
@@ -10,15 +10,8 @@ def process(items):
-    result = []
-    for item in items:
-        if item is not None:
-            result.append(transform(item))
-    return result
+    return [transform(item) for item in items if item is not None]
"""

DIFF_CONDITION_ONLY = """\
--- a/src/order/validator.py
+++ b/src/order/validator.py
@@ -22,7 +22,7 @@ def validate_order(order):
-    if order.quantity > 0:
+    if order.quantity >= 1:
         return True
"""

# ---------------------------------------------------------------------------
# Mock commits
# ---------------------------------------------------------------------------

MOCK_COMMITS: list[CommitInfo] = [

    # ── Human-style bug fixes ────────────────────────────────────────────
    _commit("fix login bug",
            "Somchai K.", ["src/auth/login.py"], days_ago=10),

    _commit("แก้ crash ตอน logout",
            "Nattaporn P.", ["src/auth/logout.py", "src/session.py"], days_ago=9),

    _commit("hotfix: payment page not loading",
            "Somchai K.", ["src/payment/views.py"], days_ago=8),

    _commit("patch null pointer in user profile",
            "Apinya W.", ["src/user/profile.py"], DIFF_NULL_CHECK, days_ago=8),

    _commit("revert: broken migration in v2.3.1",
            "Nattaporn P.", ["db/migrations/0023_auto.py"], days_ago=7),

    _commit("fixes #412 — dashboard chart shows wrong data",
            "Somchai K.", ["src/dashboard/charts.py"], days_ago=7),

    # ── AI-style bug fixes (fix verb + scope) ────────────────────────────
    _commit("fix(auth): resolve authentication failure when session token expires",
            "GitHub Copilot / Apinya W.",
            ["src/auth/session.py", "src/auth/token.py"], DIFF_NULL_CHECK, days_ago=6),

    _commit("fix(payment): prevent crash when gateway response is null",
            "GitHub Copilot / Somchai K.",
            ["src/payment/processor.py"], DIFF_TRY_CATCH, days_ago=6),

    _commit("fix(api): handle missing response body in error cases",
            "Claude / Nattaporn P.",
            ["src/api/client.py"], days_ago=5),

    _commit("fix(db): address memory leak in connection pool",
            "GitHub Copilot / Apinya W.",
            ["src/db/pool.py"], days_ago=5),

    _commit("fix(ui): correct the layout calculation when sidebar is collapsed",
            "Claude / Somchai K.",
            ["src/components/Sidebar.tsx", "src/styles/layout.css"], days_ago=5),

    _commit("fix(order): ensure proper cleanup of pending transactions on timeout",
            "GitHub Copilot / Nattaporn P.",
            ["src/order/manager.py"], days_ago=4),

    _commit("fix(cache): avoid duplicate key insertion causing silent data loss",
            "Claude / Apinya W.",
            ["src/cache/redis_client.py"], days_ago=4),

    _commit("fix(worker): eliminate infinite loop when queue is empty",
            "GitHub Copilot / Somchai K.",
            ["src/worker/consumer.py"], days_ago=3),

    # ── AI technical term bug fixes (HIGH confidence) ────────────────────
    _commit("resolve race condition in payment processing pipeline",
            "Claude / Nattaporn P.",
            ["src/payment/pipeline.py", "src/payment/lock.py"], days_ago=3),

    _commit("fix off-by-one error in pagination logic",
            "GitHub Copilot / Apinya W.",
            ["src/api/pagination.py"], days_ago=3),

    _commit("address null dereference in report generator",
            "Claude / Somchai K.",
            ["src/report/generator.py"], DIFF_NULL_CHECK, days_ago=2),

    _commit("prevent deadlock in concurrent order processing",
            "GitHub Copilot / Nattaporn P.",
            ["src/order/processor.py", "src/db/transaction.py"], days_ago=2),

    _commit("fix type mismatch causing incorrect total calculation",
            "Claude / Apinya W.",
            ["src/cart/total.py"], days_ago=2),

    _commit("mitigate unhandled exception in file upload handler",
            "GitHub Copilot / Somchai K.",
            ["src/upload/handler.py"], DIFF_TRY_CATCH, days_ago=2),

    # ── Edge-case language ────────────────────────────────────────────────
    _commit("handle edge case where user has no assigned role",
            "Claude / Nattaporn P.",
            ["src/auth/rbac.py"], days_ago=1),

    _commit("fix corner case in date range filter when start equals end",
            "GitHub Copilot / Apinya W.",
            ["src/reports/filter.py"], days_ago=1),

    # ── Diff-only signal (no fix keyword) ────────────────────────────────
    _commit("update token validation",
            "Somchai K.", ["src/auth/token.py"], DIFF_NULL_CHECK, days_ago=1),

    _commit("improve payment reliability",
            "Nattaporn P.", ["src/payment/processor.py"], DIFF_TRY_CATCH, days_ago=1),

    # ── Features ─────────────────────────────────────────────────────────
    _commit("feat(export): add CSV export for transaction history",
            "Apinya W.", ["src/features/export.py"], DIFF_FEATURE, days_ago=9),

    _commit("feat(dashboard): implement real-time order counter widget",
            "Somchai K.", ["src/dashboard/widgets.py", "src/ws/handler.py"], days_ago=8),

    _commit("เพิ่มระบบแจ้งเตือนผ่าน LINE",
            "Nattaporn P.", ["src/notifications/line.py"], days_ago=7),

    _commit("add dark mode toggle to user settings",
            "GitHub Copilot / Apinya W.",
            ["src/settings/theme.py", "src/components/ThemeToggle.tsx"], days_ago=6),

    _commit("introduce rate limiting middleware for public API endpoints",
            "Claude / Somchai K.",
            ["src/middleware/rate_limit.py"], days_ago=5),

    # ── Refactors ─────────────────────────────────────────────────────────
    _commit("refactor: extract payment validation into separate service",
            "Apinya W.", ["src/payment/validator.py"], DIFF_REFACTOR, days_ago=10),

    _commit("cleanup: remove unused imports across auth module",
            "Nattaporn P.", ["src/auth/login.py", "src/auth/token.py"], days_ago=8),

    _commit("refactor(db): restructure connection pool for testability",
            "GitHub Copilot / Somchai K.",
            ["src/db/pool.py", "tests/test_db.py"], days_ago=6),

    # ── Chores ────────────────────────────────────────────────────────────
    _commit("chore(deps): bump requests from 2.31.0 to 2.32.3",
            "Dependabot", ["requirements.txt"], days_ago=11),

    _commit("ci: add Python 3.12 to test matrix",
            "Nattaporn P.", [".github/workflows/test.yml"], days_ago=9),

    _commit("docs: update API authentication guide",
            "Apinya W.", ["docs/auth.md"], days_ago=7),

    _commit("test: add unit tests for pagination helper",
            "GitHub Copilot / Somchai K.",
            ["tests/test_pagination.py"], days_ago=5),

    # ── Ambiguous / Unclear ───────────────────────────────────────────────
    _commit("update user service",
            "Somchai K.", ["src/user/service.py"], days_ago=4),

    _commit("misc changes",
            "Nattaporn P.", ["src/utils/helpers.py", "src/config.py"], days_ago=3),

    _commit("wip",
            "Apinya W.", ["src/experiment.py"], days_ago=2),

    _commit("changes per code review",
            "Somchai K.",
            ["src/auth/login.py", "src/user/profile.py"], DIFF_CONDITION_ONLY, days_ago=1),
]


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Sprint Bug Fix Analyzer — local test")
    parser.add_argument("--mode",  choices=["keyword", "ollama", "claude", "gemini", "openai"], default="keyword")
    parser.add_argument("--model", default="qwen2.5:3b", help="Ollama model name (or Gemini model when --mode gemini)")
    parser.add_argument("--url",   default="http://localhost:11434", help="Ollama URL")
    parser.add_argument("--key",   default=None, help="Anthropic API key or Google API key (or set env var)")
    parser.add_argument("--vertex", action="store_true", help="Use Vertex AI instead of AI Studio for Gemini")
    parser.add_argument("--project", default=None, help="GCP project ID (for --vertex)")
    parser.add_argument("--region",  default="us-central1", help="GCP region (for --vertex)")
    args = parser.parse_args()

    sprint_name  = "Sprint 42 (Test)"
    sprint_start = "2025-01-06"
    sprint_end   = "2025-01-17"

    print("=" * 60)
    print("  Sprint Bug Fix Analyzer — LOCAL TEST MODE")
    print("=" * 60)
    print(f"\nSprint : {sprint_name}")
    print(f"Commits: {len(MOCK_COMMITS)} mock commits")

    # ── Build analyzer ────────────────────────────────────────────────────
    if args.mode == "ollama":
        from analyzers import OllamaAnalyzer, OllamaError
        print(f"Mode   : Ollama — {args.model}  ({args.url})")
        print()
        try:
            analyzer = OllamaAnalyzer(model=args.model, base_url=args.url)
        except OllamaError as exc:
            print(f"\nERROR: {exc}")
            sys.exit(1)
        step_label = f"Analysing with Ollama ({args.model})"

    elif args.mode == "claude":
        import os
        from dotenv import load_dotenv
        from analyzers import ClaudeAnalyzer
        load_dotenv()
        api_key = args.key or os.getenv("ANTHROPIC_API_KEY", "")
        if not api_key:
            print("\nERROR: Anthropic API key required.")
            print("  Set ANTHROPIC_API_KEY in .env  or pass  --key sk-ant-...")
            sys.exit(1)
        print(f"Mode   : Claude AI (cloud)")
        print()
        analyzer   = ClaudeAnalyzer(api_key)
        step_label = "Analysing with Claude"

    elif args.mode == "openai":
        import os
        from dotenv import load_dotenv
        from analyzers import OpenAIAnalyzer, OpenAIError
        load_dotenv()
        openai_model = args.model if args.model != "qwen2.5:3b" else os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        api_key = args.key or os.getenv("OPENAI_API_KEY", "")
        if not api_key:
            print("\nERROR: OpenAI API key required.")
            print("  Set OPENAI_API_KEY in .env  or pass  --key sk-...")
            sys.exit(1)
        print(f"Mode   : OpenAI ({openai_model})")
        print()
        try:
            analyzer = OpenAIAnalyzer(api_key=api_key, model=openai_model)
        except OpenAIError as exc:
            print(f"\nERROR: {exc}")
            sys.exit(1)
        step_label = f"Analysing with OpenAI ({openai_model})"

    elif args.mode == "gemini":
        import os
        from dotenv import load_dotenv
        from analyzers import GeminiAnalyzer, GeminiError
        load_dotenv()
        gemini_model = args.model if args.model != "qwen2.5:3b" else os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
        use_vertex   = args.vertex or os.getenv("GEMINI_USE_VERTEX", "false").lower() == "true"
        gcp_project  = args.project or os.getenv("GOOGLE_CLOUD_PROJECT", "")
        gcp_region   = args.region or os.getenv("GOOGLE_CLOUD_REGION", "us-central1")
        google_key   = args.key or os.getenv("GOOGLE_API_KEY", "")
        backend      = f"Vertex AI ({gcp_project})" if use_vertex else "AI Studio"
        print(f"Mode   : Gemini {gemini_model} — {backend}")
        print()
        try:
            analyzer = GeminiAnalyzer(
                api_key=google_key,
                project=gcp_project,
                region=gcp_region,
                use_vertex=use_vertex,
                model=gemini_model,
            )
        except GeminiError as exc:
            print(f"\nERROR: {exc}")
            sys.exit(1)
        step_label = f"Analysing with Gemini ({gemini_model})"

    else:
        print(f"Mode   : Keyword rules (no API key)")
        analyzer   = KeywordAnalyzer()
        step_label = "Classifying with keyword rules"

    print()

    # ── Analyse ───────────────────────────────────────────────────────────
    total = len(MOCK_COMMITS)
    print(f"[1/2] {step_label} — {total} commits...")

    BAR = 30
    def _progress(i, n, sha):
        filled = int(BAR * i / n)
        bar    = "=" * filled + "-" * (BAR - filled)
        print(f"\r  [{bar}] {i:>3}/{n}  {sha}", end="", flush=True)

    try:
        analyses = analyzer.analyze_batch(MOCK_COMMITS, on_progress=_progress)
    except Exception as exc:
        print(f"\n\nERROR: {exc}")
        sys.exit(1)
    print(f"\r  Done{' ' * (BAR + 20)}")

    bug_count     = sum(1 for a in analyses if a.is_bug_fix)
    fallback_count = sum(1 for a in analyses if a.is_fallback)
    bug_pct       = round(bug_count / len(analyses) * 100, 1)
    print(f"  Bug fixes found: {bug_count} / {len(analyses)} ({bug_pct}%)")
    if fallback_count:
        print(f"  Warning: {fallback_count} commit(s) failed analysis (fallback used)")

    # ── Console breakdown ─────────────────────────────────────────────────
    print()
    print(f"  {'Message':<60}  {'Category':<12}  {'Conf':<8}  {'BugFix'}")
    print(f"  {'-'*60}  {'-'*12}  {'-'*8}  {'-'*6}")
    for commit, analysis in zip(MOCK_COMMITS, analyses):
        mark = "✓" if analysis.is_bug_fix else " "
        msg  = commit.message[:58].ljust(60)
        print(
            f"  {msg}  {analysis.category.value:<12}  "
            f"{analysis.confidence.value:<8}  [{mark}]"
        )

    # ── Export ────────────────────────────────────────────────────────────
    print()
    print("[2/2] Generating Excel report...")
    import os
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    os.makedirs("output", exist_ok=True)
    filename  = os.path.join("output", f"bug_report_test_{args.mode}_{timestamp}.xlsx")

    generate_report(
        commits=MOCK_COMMITS,
        analyses=analyses,
        sprint_name=sprint_name,
        sprint_start=sprint_start,
        sprint_end=sprint_end,
        filepath=filename,
    )

    print(f"\n{'=' * 60}")
    print(f"  Report saved: {filename}")
    print(f"  Sheets:")
    print(f"    • Summary Dashboard  — overview + charts")
    print(f"    • Commit Details     — all {len(analyses)} commits colour-coded")
    print(f"    • Bug Fix Only       — {bug_count} bug fix commits")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
