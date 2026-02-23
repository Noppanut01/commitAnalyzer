"""
Abstract base class for all commit analyzers.

All analyzers (Claude, Gemini, Ollama, Keyword) share the same interface:
  - analyze_commit(commit)  → CommitAnalysis   (abstract — implement per backend)
  - analyze_batch(commits)  → list[CommitAnalysis]  (concrete — loops over analyze_commit)

Per-commit errors should be returned as a fallback CommitAnalysis (error field set),
NOT raised. Fatal errors (invalid API key, backend unreachable) may be raised.
"""

from abc import ABC, abstractmethod

from models import CommitAnalysis, CommitInfo


class BaseAnalyzer(ABC):
    """Common interface for all commit analyzers."""

    @abstractmethod
    def analyze_commit(self, commit: CommitInfo) -> CommitAnalysis:
        """Analyze a single commit.

        Non-fatal errors (timeout, malformed response) must be returned as a
        fallback CommitAnalysis with the ``error`` field set.
        Fatal errors (authentication failure, backend unavailable) may be raised.
        """
        ...

    def analyze_batch(
        self,
        commits: list[CommitInfo],
        on_progress=None,
    ) -> list[CommitAnalysis]:
        """Analyze a list of commits sequentially.

        Calls ``analyze_commit`` for every commit and collects results.
        Fatal exceptions from ``analyze_commit`` propagate to the caller.

        Args:
            commits:     List of CommitInfo objects to analyze.
            on_progress: Optional callable ``(current, total, short_sha)`` called
                         after each commit is processed.

        Returns:
            List of CommitAnalysis objects in the same order as ``commits``.
        """
        results: list[CommitAnalysis] = []
        for i, commit in enumerate(commits, 1):
            results.append(self.analyze_commit(commit))
            if on_progress:
                on_progress(i, len(commits), commit.commit_id[:7])
        return results
