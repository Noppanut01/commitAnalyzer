from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class Confidence(str, Enum):
    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"


class Category(str, Enum):
    BUG_FIX = "Bug Fix"
    FEATURE = "Feature"
    REFACTOR = "Refactor"
    CHORE = "Chore"
    UNCLEAR = "Unclear"


class BugType(str, Enum):
    LOGIC_ERROR = "Logic Error"
    UI_BUG = "UI Bug"
    PERFORMANCE = "Performance"
    CRASH = "Crash"
    SECURITY = "Security"
    DATA = "Data"
    INTEGRATION = "Integration"
    OTHER = "Other"
    NOT_APPLICABLE = "N/A"


class Severity(str, Enum):
    CRITICAL = "Critical"
    MAJOR = "Major"
    MINOR = "Minor"
    NOT_APPLICABLE = "N/A"


@dataclass
class SprintConfig:
    org: str
    project: str
    repo: str
    pat: str
    anthropic_api_key: str     # required only when ANALYSIS_MODE=claude
    sprint_start: str          # ISO date string "YYYY-MM-DD"
    sprint_end: str            # ISO date string "YYYY-MM-DD"
    sprint_name: str = ""      # optional label for the report
    branch: str = ""           # optional: filter by branch


@dataclass
class CommitInfo:
    commit_id: str
    author: str
    author_email: str
    date: str                  # ISO datetime string
    message: str
    files_changed: list[str] = field(default_factory=list)
    diff_text: str = ""
    from_merge_commit: str = ""  # SHA of the merge commit this was expanded from (empty = direct commit)
    is_merge_commit: bool = False  # True when this commit is itself a PR merge commit


@dataclass
class CommitAnalysis:
    commit_id: str
    is_bug_fix: bool
    confidence: Confidence
    category: Category
    bug_type: BugType
    severity: Severity
    reasoning: str
    files_changed: list[str] = field(default_factory=list)
    error: str = ""            # non-empty if analysis failed

    @property
    def is_fallback(self) -> bool:
        return bool(self.error)
