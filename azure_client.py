import difflib
import time
from base64 import b64encode

import requests

from models import CommitInfo, SprintConfig

MAX_DIFF_CHARS = 8000
MAX_FILES_PER_COMMIT = 10


class AzureAPIError(Exception):
    pass


class AzureDevOpsClient:
    def __init__(self, config: SprintConfig) -> None:
        self.config = config
        token = b64encode(f":{config.pat}".encode()).decode()
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Basic {token}",
            "Content-Type": "application/json",
        })
        self.base = (
            f"https://dev.azure.com/{config.org}/{config.project}"
            f"/_apis/git/repositories/{config.repo}"
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get(self, url: str, params: dict | None = None, retries: int = 3) -> dict:
        delay = 2
        for attempt in range(retries):
            try:
                resp = self.session.get(url, params=params, timeout=30)
            except requests.RequestException as exc:
                if attempt == retries - 1:
                    raise AzureAPIError(f"Network error: {exc}") from exc
                time.sleep(delay)
                delay *= 2
                continue

            if resp.status_code == 401:
                raise AzureAPIError(
                    "Authentication failed — check your Azure PAT (Code Read permission required)."
                )
            if resp.status_code == 404:
                raise AzureAPIError(
                    "Resource not found — verify AZURE_ORG, AZURE_PROJECT, and AZURE_REPO."
                )
            if resp.status_code in (429, 503):
                if attempt == retries - 1:
                    raise AzureAPIError(
                        f"Azure API rate-limited (HTTP {resp.status_code}) after {retries} retries."
                    )
                print(
                    f"  [Azure] HTTP {resp.status_code} — retrying in {delay}s "
                    f"(attempt {attempt + 1}/{retries})..."
                )
                time.sleep(delay)
                delay *= 2
                continue
            if not resp.ok:
                raise AzureAPIError(
                    f"Azure API error {resp.status_code}: {resp.text[:300]}"
                )
            return resp.json()

        raise AzureAPIError("Exceeded retry limit.")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_commits(self) -> list[CommitInfo]:
        """Fetch all commits in the sprint date range (handles pagination)."""
        url = f"{self.base}/commits"
        page_size = 100
        skip = 0
        all_commits: list[CommitInfo] = []

        # Azure expects dates as ISO strings; append time so it covers full days
        from_date = self.config.sprint_start + "T00:00:00Z"
        to_date = self.config.sprint_end + "T23:59:59Z"

        while True:
            params: dict = {
                "searchCriteria.fromDate": from_date,
                "searchCriteria.toDate": to_date,
                "$top": page_size,
                "$skip": skip,
                "api-version": "7.1",
            }
            if self.config.branch:
                params["searchCriteria.itemVersion.version"] = self.config.branch

            data = self._get(url, params=params)
            items = data.get("value", [])
            if not items:
                break

            for item in items:
                author = item.get("author", {})
                committer = item.get("committer", {})
                # Prefer committer date as it reflects when the commit landed
                date_str = committer.get("date") or author.get("date", "")
                all_commits.append(
                    CommitInfo(
                        commit_id=item["commitId"],
                        author=author.get("name", "Unknown"),
                        author_email=author.get("email", ""),
                        date=date_str,
                        message=item.get("comment", "").strip(),
                    )
                )

            if len(items) < page_size:
                break
            skip += page_size

        return all_commits

    def get_commit_changes(self, commit_id: str) -> list[str]:
        """Return the list of file paths changed in a commit."""
        url = f"{self.base}/commits/{commit_id}/changes"
        data = self._get(url, params={"api-version": "7.1"})
        paths: list[str] = []
        for change in data.get("changes", []):
            item = change.get("item", {})
            if item.get("gitObjectType") == "blob":
                path = item.get("path", "")
                if path:
                    paths.append(path)
        return paths

    def _get_file_content(self, commit_id: str, path: str) -> str | None:
        """Fetch raw file content at a specific commit. Returns None on failure."""
        url = f"{self.base}/items"
        params = {
            "path": path,
            "versionDescriptor.version": commit_id,
            "versionDescriptor.versionType": "commit",
            "$format": "text",
            "api-version": "7.1",
        }
        try:
            resp = self.session.get(url, params=params, timeout=30)
            if resp.status_code == 200:
                return resp.text
            return None
        except requests.RequestException:
            return None

    def _get_parent_content(self, commit_id: str, path: str) -> str | None:
        """Fetch raw file content at the parent commit. Returns None on failure."""
        # First get the parent commit ID
        url = f"{self.base}/commits/{commit_id}"
        try:
            data = self._get(url, params={"api-version": "7.1"})
        except AzureAPIError:
            return None
        parents = data.get("parents", [])
        if not parents:
            return None
        parent_id = parents[0]
        return self._get_file_content(parent_id, path)

    def get_diff_text(self, commit_id: str, files: list[str]) -> str:
        """Generate a unified-diff string for a commit, truncated to MAX_DIFF_CHARS."""
        selected_files = files[:MAX_FILES_PER_COMMIT]
        diff_parts: list[str] = []
        total_chars = 0

        for path in selected_files:
            if total_chars >= MAX_DIFF_CHARS:
                diff_parts.append(
                    f"\n... [truncated — {len(files) - len(selected_files)} more file(s)] ..."
                )
                break

            before = self._get_parent_content(commit_id, path)
            after = self._get_file_content(commit_id, path)

            # Detect binary files
            if after is not None and "\x00" in after[:512]:
                diff_parts.append(f"\n--- {path}\n[Binary file]\n")
                total_chars += len(diff_parts[-1])
                continue

            before_lines = (before or "").splitlines(keepends=True)
            after_lines = (after or "").splitlines(keepends=True)

            diff = list(
                difflib.unified_diff(
                    before_lines,
                    after_lines,
                    fromfile=f"a{path}",
                    tofile=f"b{path}",
                    lineterm="",
                )
            )

            if not diff:
                continue

            diff_text = "\n".join(diff)
            remaining = MAX_DIFF_CHARS - total_chars
            if len(diff_text) > remaining:
                diff_text = diff_text[:remaining] + "\n... [diff truncated] ..."

            diff_parts.append(diff_text)
            total_chars += len(diff_text)

        return "\n".join(diff_parts) if diff_parts else "(no textual diff available)"

    def enrich_commits(
        self,
        commits: list[CommitInfo],
        on_progress=None,
        fetch_diff: bool = True,
    ) -> list[CommitInfo]:
        """Fetch changed files (and optionally diff) for every commit in-place.

        fetch_diff=False skips the expensive per-file content calls — useful for
        keyword mode which only needs the file list for BugType classification.
        """
        for i, commit in enumerate(commits, 1):
            try:
                commit.files_changed = self.get_commit_changes(commit.commit_id)
                if fetch_diff:
                    commit.diff_text = self.get_diff_text(
                        commit.commit_id, commit.files_changed
                    )
            except AzureAPIError as exc:
                if fetch_diff:
                    commit.diff_text = f"[Error fetching diff: {exc}]"
            if on_progress:
                on_progress(i, len(commits), commit.commit_id[:7])
        return commits
