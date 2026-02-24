"""
Keyword-based commit classifier — no API key required.

Analyses commit message (and optionally the diff) using regex patterns
to produce the same CommitAnalysis output as the AI analyzers.

Signal tiers
────────────
HIGH   : conventional-commit fix prefix  |  issue reference  |  tech bug term
MEDIUM : general bug/fix keywords  |  AI-style fix verbs + problem object
LOW    : diff-only signals (null check, try/catch added)
"""

import re

from analyzers.base import BaseAnalyzer
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
    r"^\s*(fix|bugfix|bug-fix|hotfix|hot-fix|hotpatch|patch|revert|rollback|security|sec)\s*[:\(]",
    re.IGNORECASE,
)

# Issue / PR reference   fixes #123   closes #456   resolves #789
_ISSUE_REF = re.compile(
    r"\b(fix(es|ed)?|close[sd]?|resolve[sd]?)\s+#\d+",
    re.IGNORECASE,
)

# Technical bug terms — specific enough that they almost always mean a bug fix
_TECH_BUG_TERMS = re.compile(
    r"\b("
    r"race.?condition|data.?race|"
    r"null.?pointer|null.?dereference|null.?reference|nil.?pointer|nil.?dereference|"
    r"npe|NullPointerException|ClassCastException|concurrent.?modification|"
    r"memory.?leak|use.?after.?free|buffer.?overflow|integer.?overflow|"
    r"off.by.one|stack.?overflow|heap.?corruption|"
    r"deadlock|livelock|infinite.?loop|"
    r"unhandled.?exception|uncaught.?exception|"
    r"type.?mismatch|undefined.?behav|"
    r"double.?free|dangling.?pointer|"
    r"segfault|segmentation.?fault|"
    r"index.?out.?of.?bounds|array.?out.?of.?bounds|array.?index.?error|"
    r"division.?by.?zero|divide.?by.?zero|zero.?division|"
    r"assertion.?error|assertion.?fail|assert.?fail|"
    r"thread.?unsafe|concurrency.?issue|thread.?safety.?issue|"
    r"out.?of.?memory|oom"
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
    r"workaround|broken|typo|glitch|anomaly|defect|flaw|"
    r"mismatch(ed)?|malform(ed)?|invalid.?input|stale.?cache|"
    r"rollback|oops|symptom|unexpected.?behav|bad.?request|"
    r"misconfigur(ed|ation)?|mis.?match)\b"
    r"|(แก้|แก้ไข|แก้บัค|แก้ปัญหา|ซ่อม|แก้ด่วน|พัง|เสีย|ผิดพลาด|ไม่ทำงาน|ตกหล่น|crash)",
    re.IGNORECASE,
)

# AI-style verbs paired with a problem-indicating object
_AI_BUG_VERBS = re.compile(
    r"\b(resolv(e[sd]?|ing)|address(es|ed|ing)?|prevent(s|ed|ing)?|"
    r"avoid(s|ed|ing)?|mitigat(e[sd]?|ing)|eliminat(e[sd]?|ing)|"
    r"protect(s|ed|ing)?.{0,20}(against|from)|guard(s|ed|ing)?.{0,20}against|"
    r"recover(s|ed|ing)?.{0,20}(from|after)|fallback.{0,20}(for|when)|"
    r"sanitiz(e[sd]?|ing)|sanitiz(e[sd]?|ing))\b"
    r".{0,60}"
    r"\b(issue|bug|error|exception|crash|failure|problem|fault|"
    r"incorrect|wrong|broken|leak|race|deadlock|loop|overflow|"
    r"injection|attack|vulnerability|exploit)\b"
    r"|\bhandle\b.{0,40}\b(missing|null|undefined|invalid|empty|incorrect|malformed|"
    r"duplicate|expired|unauthorized|forbidden)\b"
    r"|\bcorrect\b.{0,40}\b(logic|behavi[ou]r|calculation|condition|handling|result|"
    r"order|sequence|format|output)\b"
    r"|\bensure\b.{0,40}\b(proper|correct|valid|does\s+not|no\s+longer|consistent)\b"
    r"|\bvalidat(e|es|ed|ing)\b.{0,40}\b(input|param|request|form|field|data|payload)\b",
    re.IGNORECASE | re.DOTALL,
)

# Edge-case / boundary language
_EDGE_CASE_WORDS = re.compile(
    r"\b(edge.?case|corner.?case|boundary.?condition|out.?of.?bounds|"
    r"missing.?case|unhandled.?case|unexpected.?input|"
    r"concurrent.?access|simultaneous|reentr(ant|y)|"
    r"race.?window|timing.?issue|off.?by.?one.?error)\b",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# ── Non-bug category patterns ────────────────────────────────────────────────
# ---------------------------------------------------------------------------

_FEATURE_WORDS = re.compile(
    r"^\s*(feat|feature|add|new|implement|create|introduce|support|enable|"
    r"extend|enhance|expose|scaffold|bootstrap|integrate)\s*[:\(]"
    r"|\b(new feature|implement|add support|initial support)\b"
    r"|(เพิ่ม|สร้าง|พัฒนา|รองรับ|เพิ่มความสามารถ)",
    re.IGNORECASE,
)

_REFACTOR_WORDS = re.compile(
    r"^\s*(refactor|cleanup|clean.?up|restructure|reorganize|reorganise|"
    r"rename|move|simplify|extract|inline|dedup|deduplicate|consolidate|"
    r"tidy|polish|streamline|modularize|modularise|decompose|split)\s*[:\(]"
    r"|\brefactor(ing|ed)?\b"
    r"|(ปรับโค้ด|จัดระเบียบโค้ด)",
    re.IGNORECASE,
)

_CHORE_WORDS = re.compile(
    r"^\s*(chore|build|ci|cd|deps?|test|docs?|style|release|bump|"
    r"update|upgrade|lint|format|config|env|setup|migrate|revert)\s*[:\(]"
    r"|\b(dependency|dependencies|upgrade|bump|merge|readme|changelog|"
    r"lockfile|package.?lock|yarn.?lock|poetry.?lock|"
    r"dockerfile|docker.?compose|makefile|gitignore|git.?hook|"
    r"eslint|prettier|tslint|flake8|pylint|black|isort|mypy|"
    r"pin.?version|pin.?dep|audit|boilerplate|scaffold|typings?|type.?def|"
    r"snapshot.?update|test.?fixture|mock.?data)\b"
    r"|(อัปเดต|อัพเดต)",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# ── Bug type classifier ──────────────────────────────────────────────────────
# ---------------------------------------------------------------------------

_BUG_TYPE_PATTERNS: list[tuple[BugType, re.Pattern]] = [
    (BugType.SECURITY, re.compile(
        r"\b(security|vulnerabilit|cve|auth(entication|orization)?|permission|"
        r"inject(ion)?|sql.?inject|sqli|nosql.?inject|xss|csrf|cors|csp|"
        r"path.?travers|directory.?travers|rce|remote.?code.?exec|ssrf|"
        r"idor|privilege.?escalat|open.?redirect|deserializ|"
        r"token|secret|credential|api.?key|password.?leak|"
        r"encrypt|decrypt|ssl|tls|certificate|"
        r"buffer.?overflow|integer.?overflow|use.?after.?free|"
        r"sanitiz|escape.?html|input.?validation)\b",
        re.IGNORECASE,
    )),
    (BugType.CRASH, re.compile(
        r"\b(crash|exception|null.?pointer|null.?dereference|nil.?pointer|"
        r"undefined|traceback|segfault|segmentation.?fault|panic|fatal|abort|"
        r"hang|freeze|unresponsive|NPE|npe|"
        r"stack.?overflow|infinite.?loop|deadlock|out.?of.?memory|OOM|oom|"
        r"assertion.?fail|assertion.?error|process.?crash|app.?crash|"
        r"force.?close|app.?not.?respond)\b",
        re.IGNORECASE,
    )),
    (BugType.PERFORMANCE, re.compile(
        r"\b(performance|slow|timeout|memory.?leak|leak|latency|"
        r"bottleneck|optimiz|OOM|oom|race.?condition|livelock|"
        r"n\+1|n\s*\+\s*1|cache.?miss|cache.?invalidat|"
        r"high.?cpu|cpu.?spike|memory.?pressure|resource.?exhaust|"
        r"slow.?query|query.?slow|response.?time|load.?time|"
        r"throttl|rate.?limit|debounce|garbage.?collect|gc.?pressure)\b",
        re.IGNORECASE,
    )),
    (BugType.UI_BUG, re.compile(
        r"\b(ui|display|style|layout|render|visual|icon|button|"
        r"label|css|alignment|overlap|flicker|truncat|"
        r"tooltip|modal|dialog|popup|popover|"
        r"scroll|scrollbar|resize|responsive|mobile|tablet|"
        r"dark.?mode|theme|animation|transition|"
        r"spacing|padding|margin|font|typography|"
        r"z.?index|viewport|overflow.?hidden|clip)\b",
        re.IGNORECASE,
    )),
    (BugType.DATA, re.compile(
        r"\b(data|database|db|migration|schema|query|sql|record|"
        r"corrupt|lost|heap.?corruption|double.?free|"
        r"transaction|constraint|foreign.?key|primary.?key|unique.?key|"
        r"duplicate.?record|duplicate.?key|"
        r"orm|serializ|deserializ|encoding|charset|utf|unicode|"
        r"nan|null.?value|empty.?field|missing.?field|"
        r"data.?loss|data.?mismatch|wrong.?data|stale.?data)\b",
        re.IGNORECASE,
    )),
    (BugType.INTEGRATION, re.compile(
        r"\b(api|integration|connection|network|request|response|"
        r"endpoint|webhook|socket|timeout|"
        r"http|rest|graphql|grpc|rpc|soap|"
        r"retry|backoff|circuit.?breaker|"
        r"ssl|tls|certificate|proxy|gateway|"
        r"kafka|redis|queue|message.?queue|rabbitmq|mq|"
        r"dns|hostname|ip.?address|cors|auth.?error|401|403|500)\b",
        re.IGNORECASE,
    )),
    (BugType.LOGIC_ERROR, re.compile(
        r"\b(logic|condition|calculat|wrong|incorrect|result|"
        r"off.by.one|boundary|edge.?case|corner.?case|type.?mismatch|"
        r"undefined.?behav|missing.?case|"
        r"comparison|comparator|sorting|ordering|"
        r"filter.?logic|pagination|business.?logic|"
        r"state.?machine|state.?transition|"
        r"rounding|precision|floating.?point|"
        r"validation.?logic|flag.?logic|toggle|"
        r"typo|copy.?paste|hardcod)\b",
        re.IGNORECASE,
    )),
]

# ---------------------------------------------------------------------------
# ── Severity signals ─────────────────────────────────────────────────────────
# ---------------------------------------------------------------------------

_CRITICAL_WORDS = re.compile(
    r"\b(critical|urgent|emergency|hotfix|hot.?patch|"
    r"security|vulnerabilit|exploit|breach|compromis|"
    r"data.?loss|data.?corrupt|production.?down|prod.?down|outage|downtime|"
    r"p0|p1|sev.?0|sev.?1|blocker|"
    r"crash|corrupt|deadlock|null.?dereference|segfault|oom|"
    r"buffer.?overflow|use.?after.?free|infinite.?loop|"
    r"system.?crash|app.?crash|process.?crash|fatal)\b",
    re.IGNORECASE,
)
_MAJOR_WORDS = re.compile(
    r"\b(major|broken|failure|incorrect|wrong|fails|cannot|unable|"
    r"race.?condition|memory.?leak|stack.?overflow|off.by.one|"
    r"unhandled|type.?mismatch|"
    r"regression|not.?working|no.?longer.?work|doesn.?t.?work|"
    r"data.?mismatch|wrong.?data|incorrect.?data|missing.?data|"
    r"duplicate.?record|bad.?request|invalid.?state|"
    r"calculation.?error|logic.?error|wrong.?result)\b",
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


_SIGNAL_EN: dict[str, str] = {
    "strong_prefix":  "conventional commit fix prefix",
    "issue_ref":      "issue reference (#)",
    "tech_term":      "technical bug indicator keyword",
    "bug_word":       "bug/fix keyword in commit message",
    "ai_verb":        "fix verb + problem description",
    "edge_case":      "edge/boundary case language",
    "null_check":     "null check added in diff",
    "try_catch":      "try/catch added in diff",
    "diff_only":      "diff pattern only (no fix keyword)",
}


def _build_reasoning(msg: str, is_bug_fix: bool, category: Category,
                     confidence: Confidence, diff: str) -> str:
    if is_bug_fix:
        signals: list[str] = []
        if _STRONG_BUG_PREFIXES.search(msg):
            signals.append(_SIGNAL_EN["strong_prefix"])
        if _ISSUE_REF.search(msg):
            signals.append(_SIGNAL_EN["issue_ref"])
        if _TECH_BUG_TERMS.search(msg):
            signals.append(_SIGNAL_EN["tech_term"])
        if _BUG_WORDS.search(msg):
            signals.append(_SIGNAL_EN["bug_word"])
        if _AI_BUG_VERBS.search(msg):
            signals.append(_SIGNAL_EN["ai_verb"])
        if _EDGE_CASE_WORDS.search(msg):
            signals.append(_SIGNAL_EN["edge_case"])
        if _DIFF_NULL_CHECK.search(diff):
            signals.append(_SIGNAL_EN["null_check"])
        if _DIFF_TRY_CATCH.search(diff):
            signals.append(_SIGNAL_EN["try_catch"])
        signal_str = ", ".join(signals) if signals else _SIGNAL_EN["diff_only"]
        conf_note  = f" (confidence: {confidence.value})" \
                     if confidence != Confidence.HIGH else ""
        return f"Classified as Bug Fix based on: {signal_str}{conf_note}"
    else:
        return f"No bug fix signals found — classified as {category.value} from commit message keywords"


# ---------------------------------------------------------------------------
# Public analyzer class  (same interface as ClaudeAnalyzer)
# ---------------------------------------------------------------------------

class KeywordAnalyzer(BaseAnalyzer):
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
