"""
Google Gemini analyzer — supports AI Studio and Vertex AI.

  AI Studio (free quota / pay-per-token):
      GOOGLE_API_KEY=AIzaSy...         (get from aistudio.google.com)

  Vertex AI (Google Cloud credits):
      GOOGLE_CLOUD_PROJECT=my-gcp-project
      GOOGLE_CLOUD_REGION=us-central1   # optional, default us-central1
      GEMINI_USE_VERTEX=true
      # Authenticate first:  gcloud auth application-default login

Recommended models:
  gemini-2.0-flash          — fast + cheap (default)
  gemini-1.5-flash          — slightly older, very reliable
  gemini-1.5-pro            — best quality, costs more
"""

import json
import time

from google import genai
from google.genai import types

from models import (
    BugType,
    Category,
    CommitAnalysis,
    CommitInfo,
    Confidence,
    Severity,
)

DEFAULT_MODEL = "gemini-2.0-flash"

from prompt import SYSTEM_PROMPT  # noqa: E402

# JSON Schema for structured output
_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "is_bug_fix": {
            "type": "boolean",
            "description": "True if this commit is a bug fix.",
        },
        "confidence": {
            "type": "string",
            "enum": ["High", "Medium", "Low"],
        },
        "category": {
            "type": "string",
            "enum": ["Bug Fix", "Feature", "Refactor", "Chore", "Unclear"],
        },
        "bug_type": {
            "type": "string",
            "enum": [
                "Logic Error", "UI Bug", "Performance", "Crash",
                "Security", "Data", "Integration", "Other", "N/A",
            ],
        },
        "severity": {
            "type": "string",
            "enum": ["Critical", "Major", "Minor", "N/A"],
        },
        "reasoning": {
            "type": "string",
            "description": "1-2 sentence explanation of the classification.",
        },
    },
    "required": ["is_bug_fix", "confidence", "category", "bug_type", "severity", "reasoning"],
}

# ---------------------------------------------------------------------------
# Value normalizers (defensive — in case model ignores schema casing)
# ---------------------------------------------------------------------------

_CONFIDENCE_MAP = {
    "high": Confidence.HIGH, "medium": Confidence.MEDIUM, "low": Confidence.LOW,
}
_CATEGORY_MAP = {
    "bug fix": Category.BUG_FIX, "bugfix": Category.BUG_FIX, "bug_fix": Category.BUG_FIX,
    "feature": Category.FEATURE, "feat": Category.FEATURE,
    "refactor": Category.REFACTOR, "refactoring": Category.REFACTOR,
    "chore": Category.CHORE, "maintenance": Category.CHORE,
    "unclear": Category.UNCLEAR, "unknown": Category.UNCLEAR,
}
_BUG_TYPE_MAP = {
    "logic error": BugType.LOGIC_ERROR, "logic_error": BugType.LOGIC_ERROR,
    "ui bug": BugType.UI_BUG, "ui_bug": BugType.UI_BUG, "ui": BugType.UI_BUG,
    "performance": BugType.PERFORMANCE,
    "crash": BugType.CRASH,
    "security": BugType.SECURITY,
    "data": BugType.DATA,
    "integration": BugType.INTEGRATION,
    "other": BugType.OTHER,
    "n/a": BugType.NOT_APPLICABLE, "na": BugType.NOT_APPLICABLE, "none": BugType.NOT_APPLICABLE,
}
_SEVERITY_MAP = {
    "critical": Severity.CRITICAL,
    "major": Severity.MAJOR,
    "minor": Severity.MINOR,
    "n/a": Severity.NOT_APPLICABLE, "na": Severity.NOT_APPLICABLE, "none": Severity.NOT_APPLICABLE,
}


def _norm(value: str, mapping: dict, default):
    return mapping.get(str(value).lower().strip(), default)


# ---------------------------------------------------------------------------
# Custom exception
# ---------------------------------------------------------------------------

class GeminiError(Exception):
    pass


# ---------------------------------------------------------------------------
# Analyzer
# ---------------------------------------------------------------------------

class GeminiAnalyzer:
    def __init__(
        self,
        api_key: str = "",
        project: str = "",
        region: str = "us-central1",
        use_vertex: bool = False,
        model: str = DEFAULT_MODEL,
    ) -> None:
        self.model_name = model
        try:
            if use_vertex:
                if not project:
                    raise GeminiError(
                        "GOOGLE_CLOUD_PROJECT is required for Vertex AI mode.\n"
                        "Set it in .env and run:  gcloud auth application-default login"
                    )
                self.client = genai.Client(vertexai=True, project=project, location=region)
            else:
                if not api_key:
                    raise GeminiError(
                        "GOOGLE_API_KEY is required for Gemini AI Studio mode.\n"
                        "Get a free key at: https://aistudio.google.com/apikey"
                    )
                self.client = genai.Client(api_key=api_key)
        except GeminiError:
            raise
        except Exception as exc:
            raise GeminiError(f"Failed to initialize Gemini client: {exc}")

        self._gen_config = types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            temperature=0.1,
            response_mime_type="application/json",
            response_schema=_RESPONSE_SCHEMA,
        )

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
                response = self.client.models.generate_content(
                    model=self.model_name,
                    contents=user_message,
                    config=self._gen_config,
                )
                return self._parse(commit, response.text)

            except Exception as exc:
                err_str = str(exc).lower()

                # Fatal errors — abort entire batch
                if any(k in err_str for k in ("api key", "invalid key", "unauthenticated", "api_key_invalid")):
                    raise GeminiError(
                        "Invalid Google API key — check GOOGLE_API_KEY in .env\n"
                        f"Details: {exc}"
                    )
                if "permission_denied" in err_str or "access denied" in err_str:
                    raise GeminiError(
                        "Gemini API permission denied. Check:\n"
                        "  • AI Studio: billing limits or key restrictions\n"
                        "  • Vertex AI: run  gcloud auth application-default login\n"
                        f"Details: {exc}"
                    )

                # Retryable errors
                if any(k in err_str for k in ("quota", "rate_limit", "resource_exhausted", "429")):
                    if attempt < max_retries:
                        wait = delay * (attempt + 1)
                        print(f"\n  [Gemini] Rate limited — sleeping {wait}s before retry...")
                        time.sleep(wait)
                        continue
                    return self._fallback(commit, f"Rate limit exceeded after retries: {exc}")

                # Non-fatal errors — fallback and continue batch
                return self._fallback(commit, f"Gemini API error: {exc}")

        return self._fallback(commit, "Exceeded retry limit.")

    def _parse(self, commit: CommitInfo, text: str) -> CommitAnalysis:
        try:
            cleaned = text.strip()
            # Strip markdown fences if present
            if cleaned.startswith("```"):
                parts = cleaned.split("```")
                cleaned = parts[1] if len(parts) > 1 else parts[0]
                if cleaned.startswith("json"):
                    cleaned = cleaned[4:]
            data = json.loads(cleaned)
        except (json.JSONDecodeError, IndexError):
            return self._fallback(commit, f"Invalid JSON from Gemini: {text[:120]}")

        try:
            return CommitAnalysis(
                commit_id=commit.commit_id,
                is_bug_fix=bool(data.get("is_bug_fix", False)),
                confidence=_norm(data.get("confidence", ""), _CONFIDENCE_MAP, Confidence.LOW),
                category=_norm(data.get("category", ""), _CATEGORY_MAP, Category.UNCLEAR),
                bug_type=_norm(data.get("bug_type", ""), _BUG_TYPE_MAP, BugType.NOT_APPLICABLE),
                severity=_norm(data.get("severity", ""), _SEVERITY_MAP, Severity.NOT_APPLICABLE),
                reasoning=str(data.get("reasoning", ""))[:500],
                files_changed=commit.files_changed,
            )
        except Exception as exc:
            return self._fallback(commit, f"Parse error: {exc}")

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
        results: list[CommitAnalysis] = []
        for i, commit in enumerate(commits, 1):
            result = self.analyze_commit(commit)  # may raise GeminiError on fatal errors
            results.append(result)
            if on_progress:
                on_progress(i, len(commits), commit.commit_id[:7])
        return results
