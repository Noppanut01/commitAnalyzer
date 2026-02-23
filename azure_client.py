import difflib
import time
from base64 import b64encode
from datetime import datetime

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
        self._org_base     = f"https://dev.azure.com/{config.org}"
        self._project_base = f"https://dev.azure.com/{config.org}/{config.project}"
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
                raise AzureAPIError("Authentication failed — invalid or expired PAT.")
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
            try:
                return resp.json()
            except ValueError:
                raise AzureAPIError(
                    f"Azure returned unexpected response (HTTP {resp.status_code}). "
                    f"Check that org name and PAT are correct."
                )

        raise AzureAPIError("Exceeded retry limit.")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_repositories(self) -> list[str]:
        """Return sorted list of repository names in the project."""
        url  = f"{self._project_base}/_apis/git/repositories"
        data = self._get(url, params={"api-version": "7.1"})
        return sorted(r["name"] for r in data.get("value", []))

    def get_branches(self) -> list[str]:
        """Return sorted list of branch names for the configured repository."""
        url  = f"{self.base}/refs"
        data = self._get(url, params={"filter": "heads/", "api-version": "7.1"})
        branches = []
        for ref in data.get("value", []):
            name = ref.get("name", "")
            if name.startswith("refs/heads/"):
                branches.append(name[len("refs/heads/"):])
        return sorted(branches)

    def get_sprints(self) -> list[dict]:
        """Return sprint iterations with start/end dates.

        Tries all teams until iterations with dates are found.
        Returns list of {name, start_date, end_date} sorted newest-first.
        """
        # Step 1 — list teams
        teams_url  = f"{self._org_base}/_apis/projects/{self.config.project}/teams"
        teams_data = self._get(teams_url, params={"api-version": "7.1"})
        teams      = [t["name"] for t in teams_data.get("value", [])]
        if not teams:
            return []

        # Step 2 — find iterations with dates (try each team)
        for team in teams:
            try:
                iter_url  = f"{self._project_base}/{team}/_apis/work/teamsettings/iterations"
                iter_data = self._get(iter_url, params={"api-version": "7.1"})
                sprints: list[dict] = []
                for item in iter_data.get("value", []):
                    attrs      = item.get("attributes") or {}
                    start_raw  = attrs.get("startDate")  or ""
                    end_raw    = attrs.get("finishDate") or ""
                    start_date = start_raw[:10]  if start_raw  else ""
                    end_date   = end_raw[:10]    if end_raw    else ""
                    sprints.append({
                        "name":       item.get("name", ""),
                        "start_date": start_date,
                        "end_date":   end_date,
                    })
                # Return only sprints that actually have dates
                dated = [s for s in sprints if s["start_date"]]
                if dated:
                    return list(reversed(dated))   # newest first
            except AzureAPIError:
                continue

        return []

    def get_organizations(self) -> list[str]:
        """Return list of Azure DevOps organisation names accessible with this PAT.

        Requires PAT scopes: User Profile (read) + Organization (read),
        or simply use Full access when creating the PAT.
        """
        try:
            profile = self._get(
                "https://app.vssps.visualstudio.com/_apis/profile/profiles/me",
                params={"api-version": "7.1"},
            )
        except AzureAPIError as exc:
            if "Authentication failed" in str(exc):
                raise AzureAPIError(
                    "Cannot browse organisations — PAT needs 'User Profile (read)' "
                    "and 'Organization (read)' scopes, or use Full access."
                )
            raise
        user_id = profile.get("id", "")
        if not user_id:
            raise AzureAPIError("Could not determine user ID from PAT.")
        data = self._get(
            "https://app.vssps.visualstudio.com/_apis/accounts",
            params={"memberId": user_id, "api-version": "7.1"},
        )
        return sorted(a["accountName"] for a in data.get("value", []))

    def get_projects(self) -> list[str]:
        """Return sorted list of project names in the organisation."""
        url  = f"{self._org_base}/_apis/projects"
        data = self._get(url, params={"api-version": "7.1", "$top": 200})
        return sorted(p["name"] for p in data.get("value", []))

    def get_commit_date_range(self, branch: str = "") -> dict:
        """Return the oldest and newest commit dates for the repository.

        Paginates through all commits (newest-first) to find the extremes.
        Capped at 100 pages × 1 000 commits = 100 000 commits.

        Returns {"start_date": "YYYY-MM-DD", "end_date": "YYYY-MM-DD"}.
        """
        url         = f"{self.base}/commits"
        base_params: dict = {"api-version": "7.1"}
        if branch:
            base_params["searchCriteria.itemVersion.version"] = branch

        page_size  = 1000
        skip       = 0
        end_date   = ""
        oldest_date = ""

        for _ in range(100):   # hard cap
            params = {**base_params, "$top": page_size, "$skip": skip}
            data   = self._get(url, params=params)
            items  = data.get("value", [])
            if not items:
                break

            if not end_date:                 # first page → newest commit
                newest   = items[0]
                end_date = (
                    newest.get("committer", {}).get("date")
                    or newest.get("author", {}).get("date", "")
                )[:10]

            # Last item on this page is the oldest commit seen so far
            last        = items[-1]
            oldest_date = (
                last.get("committer", {}).get("date")
                or last.get("author", {}).get("date", "")
            )[:10]

            if len(items) < page_size:
                break          # reached the final page
            skip += page_size

        if not end_date:
            today = datetime.now().strftime("%Y-%m-%d")
            return {"start_date": today, "end_date": today}

        return {"start_date": oldest_date or end_date, "end_date": end_date}

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
