"""
Azure OpenAI analyzer — uses Azure-hosted GPT models.

Requires an Azure OpenAI resource with a deployed model.
Set AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY, and AZURE_OPENAI_DEPLOYMENT.
"""

import json
import time

from openai import (
    APIConnectionError,
    APIError,
    AuthenticationError,
    AzureOpenAI,
    RateLimitError,
)

from analyzers.base import BaseAnalyzer
from analyzers.openai import ANALYSIS_TOOL
from models import (
    BugType,
    Category,
    CommitAnalysis,
    CommitInfo,
    Confidence,
    Severity,
)
from prompt import SYSTEM_PROMPT

DEFAULT_API_VERSION = "2024-02-01"


class AzureOpenAIError(Exception):
    pass


class AzureOpenAIAnalyzer(BaseAnalyzer):
    def __init__(
        self,
        endpoint: str,
        api_key: str,
        deployment: str,
        api_version: str = DEFAULT_API_VERSION,
    ) -> None:
        if not endpoint:
            raise AzureOpenAIError("AZURE_OPENAI_ENDPOINT is required.")
        if not api_key:
            raise AzureOpenAIError("AZURE_OPENAI_API_KEY is required.")
        if not deployment:
            raise AzureOpenAIError("AZURE_OPENAI_DEPLOYMENT is required.")

        self.client     = AzureOpenAI(
            azure_endpoint=endpoint,
            api_key=api_key,
            api_version=api_version,
        )
        self.deployment = deployment

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
                    model=self.deployment,
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
                raise AzureOpenAIError(
                    "Invalid Azure OpenAI credentials — check endpoint and API key."
                )

            except RateLimitError:
                if attempt < max_retries:
                    wait = delay * (attempt + 1)
                    print(f"\n  [Azure OpenAI] Rate limited — sleeping {wait}s before retry...")
                    time.sleep(wait)
                    continue
                return self._fallback(commit, "Rate limit exceeded after retries.")

            except APIConnectionError as exc:
                return self._fallback(commit, f"Connection error: {exc}")

            except APIError as exc:
                return self._fallback(commit, f"Azure OpenAI API error: {exc}")

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
