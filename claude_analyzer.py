import time

import anthropic

from models import (
    BugType,
    Category,
    CommitAnalysis,
    CommitInfo,
    Confidence,
    Severity,
)

MODEL = "claude-sonnet-4-6"

from prompt import SYSTEM_PROMPT  # noqa: E402

ANALYSIS_TOOL = {
    "name": "record_commit_analysis",
    "description": "Record the structured analysis of a Git commit.",
    "input_schema": {
        "type": "object",
        "properties": {
            "is_bug_fix": {
                "type": "boolean",
                "description": "True if this commit is a bug fix.",
            },
            "confidence": {
                "type": "string",
                "enum": ["High", "Medium", "Low"],
                "description": "Confidence level of the classification.",
            },
            "category": {
                "type": "string",
                "enum": ["Bug Fix", "Feature", "Refactor", "Chore", "Unclear"],
                "description": "High-level category of the commit.",
            },
            "bug_type": {
                "type": "string",
                "enum": [
                    "Logic Error",
                    "UI Bug",
                    "Performance",
                    "Crash",
                    "Security",
                    "Data",
                    "Integration",
                    "Other",
                    "N/A",
                ],
                "description": 'Type of bug. Use "N/A" for non-bug-fix commits.',
            },
            "severity": {
                "type": "string",
                "enum": ["Critical", "Major", "Minor", "N/A"],
                "description": 'Severity. Use "N/A" for non-bug-fix commits.',
            },
            "reasoning": {
                "type": "string",
                "description": "1–2 sentence explanation of the classification.",
            },
            "files_changed": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of file paths changed in this commit.",
            },
        },
        "required": [
            "is_bug_fix",
            "confidence",
            "category",
            "bug_type",
            "severity",
            "reasoning",
            "files_changed",
        ],
    },
}


class ClaudeAnalysisError(Exception):
    pass


class ClaudeAnalyzer:
    def __init__(self, api_key: str) -> None:
        self.client = anthropic.Anthropic(api_key=api_key)
        self._first_error: str = ""   # cache first error for batch reporting

    def analyze_commit(self, commit: CommitInfo) -> CommitAnalysis:
        """Analyze a single commit. Returns a fallback sentinel on failure."""
        files_str = "\n".join(commit.files_changed[:20]) if commit.files_changed else "(none)"
        user_message = (
            f"Commit ID: {commit.commit_id}\n"
            f"Author: {commit.author} <{commit.author_email}>\n"
            f"Date: {commit.date}\n"
            f"Message: {commit.message}\n\n"
            f"Files changed:\n{files_str}\n\n"
            f"Diff:\n{commit.diff_text or '(diff not available)'}"
        )

        max_retries = 2
        delay = 60

        for attempt in range(max_retries + 1):
            try:
                response = self.client.messages.create(
                    model=MODEL,
                    max_tokens=1024,
                    system=SYSTEM_PROMPT,
                    tools=[ANALYSIS_TOOL],
                    tool_choice={"type": "tool", "name": "record_commit_analysis"},
                    messages=[{"role": "user", "content": user_message}],
                )
                return self._parse_response(commit, response)

            except anthropic.AuthenticationError:
                raise ClaudeAnalysisError(
                    "Invalid Anthropic API key — check ANTHROPIC_API_KEY in .env"
                )

            except anthropic.PermissionDeniedError:
                raise ClaudeAnalysisError(
                    "Anthropic API key has no credits or insufficient permissions."
                )

            except anthropic.RateLimitError:
                if attempt < max_retries:
                    print(f"\n  [Claude] Rate limited — sleeping {delay}s before retry...")
                    time.sleep(delay)
                    continue
                return self._fallback(commit, "Claude rate limit exceeded after retries.")

            except anthropic.APIError as exc:
                return self._fallback(commit, f"Claude API error: {exc}")

        return self._fallback(commit, "Unexpected retry loop exit.")

    def _parse_response(
        self, commit: CommitInfo, response: anthropic.types.Message
    ) -> CommitAnalysis:
        for block in response.content:
            if block.type == "tool_use" and block.name == "record_commit_analysis":
                inp = block.input
                try:
                    return CommitAnalysis(
                        commit_id=commit.commit_id,
                        is_bug_fix=bool(inp["is_bug_fix"]),
                        confidence=Confidence(inp["confidence"]),
                        category=Category(inp["category"]),
                        bug_type=BugType(inp["bug_type"]),
                        severity=Severity(inp["severity"]),
                        reasoning=inp.get("reasoning", ""),
                        files_changed=inp.get("files_changed", commit.files_changed),
                    )
                except (KeyError, ValueError) as exc:
                    return self._fallback(commit, f"Malformed tool response: {exc}")

        return self._fallback(commit, "Claude did not invoke the expected tool.")

    def _fallback(self, commit: CommitInfo, reason: str) -> CommitAnalysis:
        return CommitAnalysis(
            commit_id=commit.commit_id,
            is_bug_fix=False,
            confidence=Confidence.LOW,
            category=Category.UNCLEAR,
            bug_type=BugType.NOT_APPLICABLE,
            severity=Severity.NOT_APPLICABLE,
            reasoning="Analysis unavailable — see error field.",
            files_changed=commit.files_changed,
            error=reason,
        )

    def analyze_batch(
        self,
        commits: list[CommitInfo],
        on_progress=None,
    ) -> list[CommitAnalysis]:
        """Analyse commits sequentially. Raises ClaudeAnalysisError on fatal errors."""
        results: list[CommitAnalysis] = []
        for i, commit in enumerate(commits, 1):
            result = self.analyze_commit(commit)   # may raise ClaudeAnalysisError
            results.append(result)
            if on_progress:
                on_progress(i, len(commits), commit.commit_id[:7])
        return results
