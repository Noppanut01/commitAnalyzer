"""
Ollama local LLM analyzer — no cloud API key required.

Uses Ollama's /api/chat endpoint with format="json" to get structured output.
Recommended models: qwen2.5:3b (M1 8GB), qwen2.5:7b (16GB+)
"""

import json
import time

import requests

from models import (
    BugType,
    Category,
    CommitAnalysis,
    CommitInfo,
    Confidence,
    Severity,
)

DEFAULT_URL   = "http://localhost:11434"
DEFAULT_MODEL = "qwen2.5:3b"
TIMEOUT       = 120   # seconds per request — local models can be slow


from prompt import SYSTEM_PROMPT_OLLAMA as SYSTEM_PROMPT  # noqa: E402


# ---------------------------------------------------------------------------
# Value normalizers — handle model output like "high", "BUG_FIX", "bug fix"
# ---------------------------------------------------------------------------

_CONFIDENCE_MAP = {
    "high": Confidence.HIGH, "medium": Confidence.MEDIUM, "low": Confidence.LOW,
}
_CATEGORY_MAP = {
    "bug fix": Category.BUG_FIX, "bugfix": Category.BUG_FIX, "bug_fix": Category.BUG_FIX,
    "feature": Category.FEATURE, "feat": Category.FEATURE,
    "refactor": Category.REFACTOR, "refactoring": Category.REFACTOR,
    "chore": Category.CHORE, "maintenance": Category.CHORE,
    "unclear": Category.UNCLEAR, "unknown": Category.UNCLEAR, "other": Category.UNCLEAR,
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

class OllamaError(Exception):
    pass


# ---------------------------------------------------------------------------
# Analyzer
# ---------------------------------------------------------------------------

class OllamaAnalyzer:
    def __init__(self, model: str = DEFAULT_MODEL, base_url: str = DEFAULT_URL) -> None:
        self.model    = model
        self.chat_url = f"{base_url.rstrip('/')}/api/chat"
        self._check_connection(base_url)

    def _check_connection(self, base_url: str) -> None:
        """Fail fast if Ollama isn't running or model isn't pulled."""
        try:
            resp = requests.get(f"{base_url.rstrip('/')}/api/tags", timeout=5)
            resp.raise_for_status()
        except requests.exceptions.ConnectionError:
            raise OllamaError(
                "Cannot connect to Ollama. Start it with:\n"
                "  Mac/Linux: ollama serve\n"
                "  Windows:   ollama serve  (or open Ollama app)"
            )
        except requests.RequestException as exc:
            raise OllamaError(f"Ollama health check failed: {exc}")

        available = [m["name"] for m in resp.json().get("models", [])]
        # Check both exact name and name without tag
        base_name = self.model.split(":")[0]
        match = any(
            self.model == m or m.startswith(base_name + ":") or m == base_name
            for m in available
        )
        if not match:
            raise OllamaError(
                f"Model '{self.model}' not found in Ollama.\n"
                f"Pull it with:  ollama pull {self.model}\n"
                f"Available models: {', '.join(available) or '(none)'}"
            )

    def analyze_commit(self, commit: CommitInfo) -> CommitAnalysis:
        files_str = "\n".join(commit.files_changed[:20]) if commit.files_changed else "(none)"
        user_msg = (
            f"Commit ID: {commit.commit_id[:7]}\n"
            f"Author: {commit.author}\n"
            f"Date: {commit.date[:10]}\n"
            f"Message: {commit.message}\n\n"
            f"Files changed:\n{files_str}\n\n"
            f"Diff:\n{commit.diff_text[:4000] or '(not available)'}"
        )

        payload = {
            "model":    self.model,
            "messages": [
                {"role": "system",  "content": SYSTEM_PROMPT},
                {"role": "user",    "content": user_msg},
            ],
            "format": "json",
            "stream": False,
            "options": {"temperature": 0.1, "num_predict": 256},
        }

        for attempt in range(2):
            try:
                resp = requests.post(self.chat_url, json=payload, timeout=TIMEOUT)
                resp.raise_for_status()
                content = resp.json()["message"]["content"]
                return self._parse(commit, content)

            except requests.exceptions.Timeout:
                if attempt == 0:
                    print(f"\n  [Ollama] Timeout — retrying commit {commit.commit_id[:7]}...")
                    time.sleep(2)
                    continue
                return self._fallback(commit, "Request timed out after retry.")

            except requests.exceptions.ConnectionError:
                return self._fallback(commit, "Ollama connection lost mid-batch.")

            except (KeyError, requests.RequestException) as exc:
                return self._fallback(commit, f"Ollama API error: {exc}")

        return self._fallback(commit, "Exceeded retry limit.")

    def _parse(self, commit: CommitInfo, content: str) -> CommitAnalysis:
        try:
            # Strip markdown code fences if model wraps the JSON
            cleaned = content.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("```")[1]
                if cleaned.startswith("json"):
                    cleaned = cleaned[4:]
            data = json.loads(cleaned)
        except (json.JSONDecodeError, IndexError):
            return self._fallback(commit, f"Invalid JSON from model: {content[:120]}")

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
            results.append(self.analyze_commit(commit))
            if on_progress:
                on_progress(i, len(commits), commit.commit_id[:7])
        return results
