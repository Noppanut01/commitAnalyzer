"""
Analyzer package.

Exposes all analyzer classes, their exception types, and a factory function.

Usage:
    from analyzers import get_analyzer
    analyzer = get_analyzer(mode="claude", cfg={"anthropic_api_key": "sk-ant-..."})
    analyses = analyzer.analyze_batch(commits)

    # Or import classes directly:
    from analyzers import ClaudeAnalyzer, KeywordAnalyzer
"""

from analyzers.base import BaseAnalyzer
from analyzers.claude import ClaudeAnalyzer, ClaudeAnalysisError
from analyzers.gemini import GeminiAnalyzer, GeminiError
from analyzers.keyword import KeywordAnalyzer
from analyzers.ollama import OllamaAnalyzer, OllamaError
from analyzers.openai import OpenAIAnalyzer, OpenAIError

__all__ = [
    "BaseAnalyzer",
    "ClaudeAnalyzer",
    "ClaudeAnalysisError",
    "GeminiAnalyzer",
    "GeminiError",
    "KeywordAnalyzer",
    "OllamaAnalyzer",
    "OllamaError",
    "OpenAIAnalyzer",
    "OpenAIError",
    "get_analyzer",
]


def get_analyzer(mode: str, cfg: dict) -> BaseAnalyzer:
    """Factory — return the correct analyzer for *mode* using settings from *cfg*.

    Args:
        mode: One of ``"claude"``, ``"gemini"``, ``"ollama"``, ``"keyword"``, ``"openai"``.
        cfg:  Dict of configuration values (keys match ConfigPayload field names).

    Returns:
        A ready-to-use :class:`BaseAnalyzer` instance.

    Raises:
        OllamaError:  Ollama server unreachable or model not pulled.
        GeminiError:  Gemini client misconfigured (missing key / project).
        OpenAIError:  OpenAI API key missing or invalid.
    """
    mode = (mode or "claude").strip().lower()

    if mode == "keyword":
        return KeywordAnalyzer()

    if mode == "ollama":
        return OllamaAnalyzer(
            model=(cfg.get("ollama_model") or "qwen2.5:3b").strip(),
            base_url=(cfg.get("ollama_url") or "http://localhost:11434").strip(),
        )

    if mode == "gemini":
        return GeminiAnalyzer(
            api_key=(cfg.get("google_api_key") or "").strip(),
            project=(cfg.get("google_cloud_project") or "").strip(),
            region=(cfg.get("google_cloud_region") or "us-central1").strip(),
            use_vertex=(cfg.get("gemini_use_vertex") or "false").strip().lower() == "true",
            model=(cfg.get("gemini_model") or "gemini-2.0-flash").strip(),
        )

    if mode == "openai":
        return OpenAIAnalyzer(
            api_key=(cfg.get("openai_api_key") or "").strip(),
            model=(cfg.get("openai_model") or "gpt-4o-mini").strip(),
        )

    # default: claude
    return ClaudeAnalyzer((cfg.get("anthropic_api_key") or "").strip())
