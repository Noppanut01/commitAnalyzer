"""
Keyword-based commit classifier — no API key required.

Analyses commit message (and optionally the diff) using regex patterns
to produce the same CommitAnalysis output as ClaudeAnalyzer.

Signal tiers
────────────
HIGH   : conventional-commit fix prefix  |  issue reference  |  tech bug term
MEDIUM : general bug/fix keywords  |  AI-style fix verbs + problem object
LOW    : diff-only signals (null check, try/catch added)
"""

import re

from models import (
    BugType,
    Category,
    CommitAnalysis,
    CommitInfo,
    Confidence,
    Severity,
)

# ---------------------------------------------------------------------------
# ── HIGH-confidence bug fix patterns ────────────────────────────────────────
# ---------------------------------------------------------------------------

# Conventional commit fix prefix  →  fix:  fix(:  bugfix:  hotfix(scope):  etc.
_STRONG_BUG_PREFIXES = re.compile(
    r"^\s*(fix|bugfix|bug-fix|hotfix|hot-fix|patch|revert)\s*[:\(]",
    re.IGNORECASE,
)

# Issue / PR reference   fixes #123   closes #456   resolves #789
_ISSUE_REF = re.compile(
    r"\b(fix(es|ed)?|close[sd]?|resolve[sd]?)\s+#\d+",
    re.IGNORECASE,
)

# Technical bug terms — specific enough that they almost always mean a bug fix
# (AI commits love naming these precisely)
_TECH_BUG_TERMS = re.compile(
    r"\b("
    r"race.?condition|null.?pointer|null.?dereference|null.?reference|"
    r"memory.?leak|use.?after.?free|buffer.?overflow|integer.?overflow|"
    r"off.by.one|stack.?overflow|heap.?corruption|"
    r"deadlock|livelock|infinite.?loop|"
    r"unhandled.?exception|uncaught.?exception|"
    r"type.?mismatch|undefined.?behav|"
    r"double.?free|dangling.?pointer"
    r")\b",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# ── MEDIUM-confidence bug fix patterns ──────────────────────────────────────
# ---------------------------------------------------------------------------

# Classic bug/fix keywords  (Thai keywords use no \b — word boundaries don't apply to Thai)
_BUG_WORDS = re.compile(
    r"\b(fix(es|ed|ing)?|bug(fix)?|hot.?fix|patch(ed)?|"
    r"resolv(e[sd]?|ing)|regression|revert(ed)?|repair(ed)?|correct(ed)?|"
    r"workaround)\b"
    r"|(แก้|แก้ไข|แก้บัค|แก้ปัญหา|ซ่อม|แก้ด่วน)",
    re.IGNORECASE,
)

# AI-style verbs paired with a problem-indicating object
# e.g. "resolve authentication failure", "prevent crash when token is null",
#      "handle missing response body", "address memory leak in service"
_AI_BUG_VERBS = re.compile(
    # verb  …(up to 60 chars)…  problem noun
    r"\b(resolv(e[sd]?|ing)|address(es|ed|ing)?|prevent(s|ed|ing)?|"
    r"avoid(s|ed|ing)?|mitigat(e[sd]?|ing)|eliminat(e[sd]?|ing))\b"
    r".{0,60}"
    r"\b(issue|bug|error|exception|crash|failure|problem|fault|"
    r"incorrect|wrong|broken|leak|race|deadlock|loop|overflow)\b"
    # OR: "handle missing/null/undefined/invalid X"
    r"|\bhandle\b.{0,40}\b(missing|null|undefined|invalid|empty|incorrect|malformed)\b"
    # OR: "correct the X logic / behavior / calculation"
    r"|\bcorrect\b.{0,40}\b(logic|behavi[ou]r|calculation|condition|handling|result)\b"
    # OR: "ensure proper / ensure X does not"
    r"|\bensure\b.{0,40}\b(proper|correct|valid|does\s+not|no\s+longer)\b",
    re.IGNORECASE | re.DOTALL,
)

# Edge-case / boundary language (AI loves this phrasing)
_EDGE_CASE_WORDS = re.compile(
    r"\b(edge.?case|corner.?case|boundary.?condition|out.?of.?bounds|"
    r"missing.?case|unhandled.?case|unexpected.?input)\b",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# ── Non-bug category patterns ────────────────────────────────────────────────
# ---------------------------------------------------------------------------

_FEATURE_WORDS = re.compile(
    r"^\s*(feat|feature|add|new|implement|create|introduce)\s*[:\(]"
    r"|\b(new feature|implement)\b"
    r"|(เพิ่ม|สร้าง)",
    re.IGNORECASE,
)

_REFACTOR_WORDS = re.compile(
    r"^\s*(refactor|cleanup|clean.?up|restructure|reorganize|rename|move)\s*[:\(]"
    r"|\brefactor(ing|ed)?\b",
    re.IGNORECASE,
)

_CHORE_WORDS = re.compile(
    r"^\s*(chore|build|ci|deps?|test|docs?|style|release|bump|update|upgrade)\s*[:\(]"
    r"|\b(dependency|dependencies|upgrade|bump|merge|readme|changelog)\b",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# ── Bug type classifier ──────────────────────────────────────────────────────
# ---------------------------------------------------------------------------

_BUG_TYPE_PATTERNS: list[tuple[BugType, re.Pattern]] = [
    (BugType.SECURITY, re.compile(
        r"\b(security|vulnerabilit|cve|auth|permission|inject|xss|csrf|"
        r"token|encrypt|buffer.?overflow|integer.?overflow|use.?after.?free)\b",
        re.IGNORECASE,
    )),
    (BugType.CRASH, re.compile(
        r"\b(crash|exception|null.?pointer|null.?dereference|undefined|"
        r"traceback|segfault|hang|freeze|NPE|stack.?overflow|"
        r"infinite.?loop|deadlock|out.?of.?memory|OOM)\b",
        re.IGNORECASE,
    )),
    (BugType.PERFORMANCE, re.compile(
        r"\b(performance|slow|timeout|memory.?leak|leak|latency|"
        r"bottleneck|optimize|OOM|race.?condition|livelock)\b",
        re.IGNORECASE,
    )),
    (BugType.UI_BUG, re.compile(
        r"\b(ui|display|style|layout|render|visual|icon|button|"
        r"label|css|alignment|overlap|flicker|truncat)\b",
        re.IGNORECASE,
    )),
    (BugType.DATA, re.compile(
        r"\b(data|database|db|migration|schema|query|sql|record|"
        r"corrupt|lost|heap.?corruption|double.?free)\b",
        re.IGNORECASE,
    )),
    (BugType.INTEGRATION, re.compile(
        r"\b(api|integration|connection|network|request|response|"
        r"endpoint|webhook|socket|timeout)\b",
        re.IGNORECASE,
    )),
    (BugType.LOGIC_ERROR, re.compile(
        r"\b(logic|condition|calculat|wrong|incorrect|result|"
        r"off.by.one|boundary|edge.?case|corner.?case|type.?mismatch|"
        r"undefined.?behav|missing.?case)\b",
        re.IGNORECASE,
    )),
]

# ---------------------------------------------------------------------------
# ── Severity signals ─────────────────────────────────────────────────────────
# ---------------------------------------------------------------------------

_CRITICAL_WORDS = re.compile(
    r"\b(critical|urgent|emergency|hotfix|security|vulnerabilit|"
    r"data.?loss|production|crash|corrupt|deadlock|null.?dereference|"
    r"buffer.?overflow|use.?after.?free|infinite.?loop)\b",
    re.IGNORECASE,
)
_MAJOR_WORDS = re.compile(
    r"\b(major|broken|failure|incorrect|wrong|fails|cannot|unable|"
    r"race.?condition|memory.?leak|stack.?overflow|off.by.one|"
    r"unhandled|type.?mismatch)\b",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# ── Diff-level signals ───────────────────────────────────────────────────────
# ---------------------------------------------------------------------------

_DIFF_NULL_CHECK  = re.compile(
    r"^\+.*\b(if\s+\w+\s*(is\s+None|is\s+not\s+None|== None|!= None|\?\?|== null|!= null))",
    re.MULTILINE,
)
_DIFF_TRY_CATCH   = re.compile(
    r"^\+(.*try\s*[:{]|.*catch\s*[\(\{]|.*except\s+)",
    re.MULTILINE,
)
_DIFF_COND_CHANGE = re.compile(
    r"^[-+].*\b(if|elif|else|switch)\b",
    re.MULTILINE,
)

# ---------------------------------------------------------------------------
# Core classifier
# ---------------------------------------------------------------------------

def _classify(message: str, diff: str, files: list[str]) -> CommitAnalysis:
    """Pure function — returns a CommitAnalysis with commit_id left blank."""
    msg         = message.strip()
    search_text = msg + " " + " ".join(files)

    is_bug_fix = False
    confidence = Confidence.LOW
    category   = Category.UNCLEAR

    # ── Tier 1: HIGH confidence ───────────────────────────────────────────
    if _STRONG_BUG_PREFIXES.search(msg) or _ISSUE_REF.search(msg):
        is_bug_fix = True
        confidence = Confidence.HIGH
        category   = Category.BUG_FIX

    elif _TECH_BUG_TERMS.search(msg):
        is_bug_fix = True
        confidence = Confidence.HIGH
        category   = Category.BUG_FIX

    # ── Tier 2: MEDIUM confidence ─────────────────────────────────────────
    elif _BUG_WORDS.search(msg):
        is_bug_fix = True
        confidence = Confidence.MEDIUM
        category   = Category.BUG_FIX

    elif _AI_BUG_VERBS.search(msg) or _EDGE_CASE_WORDS.search(msg):
        is_bug_fix = True
        confidence = Confidence.MEDIUM
        category   = Category.BUG_FIX

    # ── Non-bug categories ────────────────────────────────────────────────
    elif _FEATURE_WORDS.search(msg):
        category   = Category.FEATURE
        confidence = Confidence.HIGH

    elif _REFACTOR_WORDS.search(msg):
        category   = Category.REFACTOR
        confidence = Confidence.HIGH

    elif _CHORE_WORDS.search(msg):
        category   = Category.CHORE
        confidence = Confidence.HIGH

    # ── Tier 3: Diff-only signals (Unclear → LOW confidence bug fix) ──────
    if not is_bug_fix and category == Category.UNCLEAR:
        if _DIFF_NULL_CHECK.search(diff) or _DIFF_TRY_CATCH.search(diff):
            is_bug_fix = True
            category   = Category.BUG_FIX
            confidence = Confidence.LOW
        elif _DIFF_COND_CHANGE.search(diff):
            confidence = Confidence.LOW

    # Diff can upgrade MEDIUM → HIGH
    elif is_bug_fix and confidence == Confidence.MEDIUM:
        if _DIFF_NULL_CHECK.search(diff) or _DIFF_TRY_CATCH.search(diff):
            confidence = Confidence.HIGH

    # ── Bug type ──────────────────────────────────────────────────────────
    bug_type = BugType.NOT_APPLICABLE
    if is_bug_fix:
        for bt, pattern in _BUG_TYPE_PATTERNS:
            if pattern.search(search_text) or pattern.search(diff[:2000]):
                bug_type = bt
                break
        if bug_type == BugType.NOT_APPLICABLE:
            bug_type = BugType.OTHER

    # ── Severity ──────────────────────────────────────────────────────────
    severity = Severity.NOT_APPLICABLE
    if is_bug_fix:
        if _CRITICAL_WORDS.search(search_text):
            severity = Severity.CRITICAL
        elif _MAJOR_WORDS.search(search_text):
            severity = Severity.MAJOR
        else:
            severity = Severity.MINOR

    reasoning = _build_reasoning(msg, is_bug_fix, category, confidence, diff)

    return CommitAnalysis(
        commit_id="",
        is_bug_fix=is_bug_fix,
        confidence=confidence,
        category=category,
        bug_type=bug_type,
        severity=severity,
        reasoning=reasoning,
    )


def _build_reasoning(msg: str, is_bug_fix: bool, category: Category,
                     confidence: Confidence, diff: str) -> str:
    if is_bug_fix:
        signals: list[str] = []
        if _STRONG_BUG_PREFIXES.search(msg):
            signals.append("conventional-commit fix prefix")
        if _ISSUE_REF.search(msg):
            signals.append("issue reference (#)")
        if _TECH_BUG_TERMS.search(msg):
            signals.append("technical bug term in message")
        if _BUG_WORDS.search(msg):
            signals.append("bug/fix keyword in message")
        if _AI_BUG_VERBS.search(msg):
            signals.append("AI-style fix verb + problem object")
        if _EDGE_CASE_WORDS.search(msg):
            signals.append("edge/boundary case language")
        if _DIFF_NULL_CHECK.search(diff):
            signals.append("null check added in diff")
        if _DIFF_TRY_CATCH.search(diff):
            signals.append("try/catch block added in diff")
        signal_str = ", ".join(signals) if signals else "diff pattern only"
        conf_note  = f" (confidence: {confidence.value})" if confidence != Confidence.HIGH else ""
        return f"Classified as bug fix based on: {signal_str}{conf_note}."
    else:
        return (
            f"No bug-fix signals found. "
            f"Classified as {category.value} based on commit message keywords."
        )


# ---------------------------------------------------------------------------
# Public analyzer class  (same interface as ClaudeAnalyzer)
# ---------------------------------------------------------------------------

class KeywordAnalyzer:
    """Rule-based commit classifier. No API key required."""

    def analyze_commit(self, commit: CommitInfo) -> CommitAnalysis:
        result = _classify(
            message=commit.message,
            diff=commit.diff_text,
            files=commit.files_changed,
        )
        result.commit_id     = commit.commit_id
        result.files_changed = commit.files_changed
        return result

    def analyze_batch(
        self,
        commits: list[CommitInfo],
        on_progress=None,
    ) -> list[CommitAnalysis]:
        results: list[CommitAnalysis] = []
        for i, commit in enumerate(commits, 1):
            results.append(self.analyze_commit(commit))
            if on_progress:
                on_progress(i, len(commits), commit.commit_id[:7])
        return results
