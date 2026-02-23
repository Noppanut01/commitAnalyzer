"""
OpenAI analyzer — GPT-4o-mini, GPT-4o, o3-mini, etc.

Get an API key at: https://platform.openai.com/api-keys
"""

import json
import time

from openai import (
    APIConnectionError,
    APIError,
    AuthenticationError,
    OpenAI,
    RateLimitError,
)

from analyzers.base import BaseAnalyzer
from models import (
    BugType,
    Category,
    CommitAnalysis,
    CommitInfo,
    Confidence,
    Severity,
)
from prompt import SYSTEM_PROMPT

DEFAULT_MODEL = "gpt-4o-mini"

ANALYSIS_TOOL = {
    "type": "function",
    "function": {
        "name": "record_commit_analysis",
        "description": "Record the structured analysis of a Git commit.",
        "parameters": {
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
                        "Logic Error", "UI Bug", "Performance", "Crash",
                        "Security", "Data", "Integration", "Other", "N/A",
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
                "is_bug_fix", "confidence", "category", "bug_type",
                "severity", "reasoning", "files_changed",
            ],
        },
    },
}


class OpenAIError(Exception):
    pass


class OpenAIAnalyzer(BaseAnalyzer):
    def __init__(self, api_key: str, model: str = DEFAULT_MODEL) -> None:
        if not api_key:
            raise OpenAIError(
                "OPENAI_API_KEY is required.\n"
                "Get a key at: https://platform.openai.com/api-keys"
            )
        self.client = OpenAI(api_key=api_key)
        self.model  = model

    def analyze_commit(self, commit: CommitInfo) -> CommitAnalysis:
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
        delay = 30

        for attempt in range(max_retries + 1):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    max_tokens=1024,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user",   "content": user_message},
                    ],
                    tools=[ANALYSIS_TOOL],
                    tool_choice={
                        "type": "function",
                        "function": {"name": "record_commit_analysis"},
                    },
                )
                return self._parse_response(commit, response)

            except AuthenticationError:
                raise OpenAIError(
                    "Invalid OpenAI API key — check OPENAI_API_KEY.\n"
                    "Get a key at: https://platform.openai.com/api-keys"
                )

            except RateLimitError:
                if attempt < max_retries:
                    wait = delay * (attempt + 1)
                    print(f"\n  [OpenAI] Rate limited — sleeping {wait}s before retry...")
                    time.sleep(wait)
                    continue
                return self._fallback(commit, "Rate limit exceeded after retries.")

            except APIConnectionError as exc:
                return self._fallback(commit, f"Connection error: {exc}")

            except APIError as exc:
                return self._fallback(commit, f"OpenAI API error: {exc}")

        return self._fallback(commit, "Exceeded retry limit.")

    def _parse_response(self, commit: CommitInfo, response) -> CommitAnalysis:
        message = response.choices[0].message
        if not message.tool_calls:
            return self._fallback(commit, "Model did not invoke the expected tool.")

        tool_call = message.tool_calls[0]
        if tool_call.function.name != "record_commit_analysis":
            return self._fallback(commit, f"Unexpected tool: {tool_call.function.name}")

        try:
            inp = json.loads(tool_call.function.arguments)
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
        except (KeyError, ValueError, json.JSONDecodeError) as exc:
            return self._fallback(commit, f"Malformed tool response: {exc}")

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
