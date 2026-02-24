"""
Unit tests for merge-commit expansion logic in AzureDevOpsClient.

Covers:
  - _get_commit_parents
  - _get_pr_inner_commits
  - _expand_merge_commits  (recursive)
  - enrich_commits         (integration)
"""

import unittest
from unittest.mock import MagicMock, patch, call
from models import CommitInfo, SprintConfig
from azure_client import AzureDevOpsClient, AzureAPIError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_client() -> AzureDevOpsClient:
    config = SprintConfig(
        org="test-org",
        project="test-project",
        repo="test-repo",
        pat="fake-pat",
        anthropic_api_key="",
        sprint_start="2025-01-01",
        sprint_end="2025-01-31",
    )
    client = AzureDevOpsClient(config)
    return client


def _commit(commit_id: str, message: str = "", author: str = "Dev") -> CommitInfo:
    return CommitInfo(
        commit_id=commit_id,
        author=author,
        author_email="dev@test.com",
        date="2025-01-10T00:00:00Z",
        message=message,
    )


# ---------------------------------------------------------------------------
# _get_commit_parents
# ---------------------------------------------------------------------------

class TestGetCommitParents(unittest.TestCase):

    def test_returns_parents_list(self):
        client = _make_client()
        client._get = MagicMock(return_value={"parents": ["aaa", "bbb"]})

        result = client._get_commit_parents("ccc")

        self.assertEqual(result, ["aaa", "bbb"])

    def test_returns_empty_on_api_error(self):
        client = _make_client()
        client._get = MagicMock(side_effect=AzureAPIError("not found"))

        result = client._get_commit_parents("ccc")

        self.assertEqual(result, [])

    def test_returns_empty_when_no_parents_key(self):
        client = _make_client()
        client._get = MagicMock(return_value={})

        result = client._get_commit_parents("ccc")

        self.assertEqual(result, [])


# ---------------------------------------------------------------------------
# _get_pr_inner_commits
# ---------------------------------------------------------------------------

class TestGetPrInnerCommits(unittest.TestCase):

    def _api_response(self, commit_ids: list[str]) -> dict:
        return {
            "value": [
                {
                    "commitId": cid,
                    "author": {"name": "Dev", "email": "dev@test.com", "date": "2025-01-10T00:00:00Z"},
                    "committer": {"date": "2025-01-10T00:00:00Z"},
                    "comment": f"commit {cid}",
                }
                for cid in commit_ids
            ]
        }

    def test_returns_commits_between_base_and_head(self):
        client = _make_client()
        client._get = MagicMock(return_value=self._api_response(["c1", "c2"]))

        result = client._get_pr_inner_commits("base123", "head456")

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].commit_id, "c1")
        self.assertEqual(result[1].commit_id, "c2")

    def test_returns_empty_on_api_error(self):
        client = _make_client()
        client._get = MagicMock(side_effect=AzureAPIError("timeout"))

        result = client._get_pr_inner_commits("base123", "head456")

        self.assertEqual(result, [])

    def test_returns_empty_when_no_value(self):
        client = _make_client()
        client._get = MagicMock(return_value={})

        result = client._get_pr_inner_commits("base123", "head456")

        self.assertEqual(result, [])

    def test_passes_correct_params(self):
        client = _make_client()
        client._get = MagicMock(return_value={"value": []})

        client._get_pr_inner_commits("baseAAA", "headBBB")

        call_args = client._get.call_args
        passed_params = call_args[0][1] if len(call_args[0]) > 1 else call_args[1].get("params", {})
        self.assertEqual(passed_params["searchCriteria.itemVersion.version"], "headBBB")
        self.assertEqual(passed_params["searchCriteria.compareVersion.version"], "baseAAA")
        # sprint date filter must be included
        self.assertEqual(passed_params["searchCriteria.fromDate"], "2025-01-01T00:00:00Z")
        self.assertEqual(passed_params["searchCriteria.toDate"], "2025-01-31T23:59:59Z")


# ---------------------------------------------------------------------------
# _expand_merge_commits
# ---------------------------------------------------------------------------

class TestExpandMergeCommits(unittest.TestCase):

    def test_regular_commit_passes_through(self):
        """A commit with 1 parent should be kept as-is."""
        client = _make_client()
        client._get_commit_parents = MagicMock(return_value=["parent1"])
        client._get_pr_inner_commits = MagicMock()

        commits = [_commit("abc")]
        result = client._expand_merge_commits(commits, set())

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].commit_id, "abc")
        client._get_pr_inner_commits.assert_not_called()

    def test_merge_commit_expanded_to_pr_commits(self):
        """A merge commit (2 parents) should be replaced by its PR inner commits."""
        client = _make_client()

        def fake_parents(cid):
            # only "merge" is a merge commit; pr1/pr2 are regular commits
            return ["base", "head"] if cid == "merge" else ["prev"]

        client._get_commit_parents = MagicMock(side_effect=fake_parents)
        client._get_pr_inner_commits = MagicMock(
            return_value=[_commit("pr1"), _commit("pr2")]
        )

        result = client._expand_merge_commits([_commit("merge")], set())

        self.assertEqual(len(result), 2)
        self.assertEqual({c.commit_id for c in result}, {"pr1", "pr2"})

    def test_merge_commit_fallback_when_expansion_empty(self):
        """If PR inner commits returns empty, keep the original merge commit."""
        client = _make_client()
        client._get_commit_parents = MagicMock(return_value=["base", "head"])
        client._get_pr_inner_commits = MagicMock(return_value=[])

        result = client._expand_merge_commits([_commit("merge")], set())

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].commit_id, "merge")

    def test_mixed_regular_and_merge_commits(self):
        """Regular commits pass through; merge commits are expanded."""
        client = _make_client()

        def fake_parents(cid):
            return ["base", "head"] if cid == "merge" else ["prev"]

        client._get_commit_parents = MagicMock(side_effect=fake_parents)
        client._get_pr_inner_commits = MagicMock(
            return_value=[_commit("pr1"), _commit("pr2")]
        )

        commits = [_commit("regular"), _commit("merge")]
        result = client._expand_merge_commits(commits, set())

        ids = [c.commit_id for c in result]
        self.assertIn("regular", ids)
        self.assertIn("pr1", ids)
        self.assertIn("pr2", ids)
        self.assertNotIn("merge", ids)

    def test_deduplication_via_seen_ids(self):
        """Commits already in seen_ids should be skipped."""
        client = _make_client()
        client._get_commit_parents = MagicMock(return_value=["prev"])

        seen = {"abc"}
        result = client._expand_merge_commits([_commit("abc"), _commit("xyz")], seen)

        ids = [c.commit_id for c in result]
        self.assertNotIn("abc", ids)
        self.assertIn("xyz", ids)

    def test_deduplication_across_expansion(self):
        """PR inner commit that was already seen directly should not be added twice."""
        client = _make_client()

        def fake_parents(cid):
            return ["base", "head"] if cid == "merge" else ["prev"]

        client._get_commit_parents = MagicMock(side_effect=fake_parents)
        # pr1 already appears as a standalone commit before the merge commit
        client._get_pr_inner_commits = MagicMock(
            return_value=[_commit("pr1"), _commit("pr2")]
        )

        commits = [_commit("pr1"), _commit("merge")]
        result = client._expand_merge_commits(commits, set())

        ids = [c.commit_id for c in result]
        self.assertEqual(ids.count("pr1"), 1)
        self.assertIn("pr2", ids)

    def test_nested_merge_commit_recursive_expansion(self):
        """A merge commit inside a PR should also be expanded (nested PR case)."""
        client = _make_client()

        # outer-merge → [inner-merge, regular-pr]
        # inner-merge → [deep1, deep2]
        def fake_parents(cid):
            if cid in ("outer-merge", "inner-merge"):
                return ["base", "head"]
            return ["prev"]

        def fake_inner(base, head):
            if "outer" in base or "outer" in head:  # won't match this way
                pass
            # We identify by which merge commit called us via call order
            calls = client._get_pr_inner_commits.call_count
            if calls == 1:  # first call: expand outer-merge
                return [_commit("inner-merge"), _commit("regular-pr")]
            else:            # second call: expand inner-merge
                return [_commit("deep1"), _commit("deep2")]

        client._get_commit_parents = MagicMock(side_effect=fake_parents)
        client._get_pr_inner_commits = MagicMock(side_effect=fake_inner)

        result = client._expand_merge_commits([_commit("outer-merge")], set())

        ids = {c.commit_id for c in result}
        self.assertIn("regular-pr", ids)
        self.assertIn("deep1", ids)
        self.assertIn("deep2", ids)
        self.assertNotIn("outer-merge", ids)
        self.assertNotIn("inner-merge", ids)

    def test_max_depth_stops_recursion(self):
        """When depth > max_depth, commits are returned as-is with no API calls."""
        client = _make_client()
        client._get_commit_parents = MagicMock()
        client._get_pr_inner_commits = MagicMock()

        # Call directly at depth beyond limit
        result = client._expand_merge_commits(
            [_commit("a"), _commit("b")], set(), depth=6, max_depth=5
        )

        ids = {c.commit_id for c in result}
        self.assertEqual(ids, {"a", "b"})
        client._get_commit_parents.assert_not_called()
        client._get_pr_inner_commits.assert_not_called()

    def test_max_depth_prevents_deeper_expansion(self):
        """Recursion at depth=max_depth+1 returns commits without further expansion."""
        client = _make_client()

        def fake_parents(cid):
            return ["base", "head"] if cid == "root" else ["prev"]

        client._get_commit_parents = MagicMock(side_effect=fake_parents)
        client._get_pr_inner_commits = MagicMock(return_value=[_commit("inner")])

        # max_depth=0: expanding root at depth=0 is allowed (0 > 0 is False),
        # but recursion at depth=1 hits early return and returns inner as-is
        result = client._expand_merge_commits(
            [_commit("root")], set(), depth=0, max_depth=0
        )

        ids = {c.commit_id for c in result}
        self.assertIn("inner", ids)
        self.assertNotIn("root", ids)

    def test_initial_commit_no_parents(self):
        """A commit with no parents (initial repo commit) should pass through."""
        client = _make_client()
        client._get_commit_parents = MagicMock(return_value=[])

        result = client._expand_merge_commits([_commit("init")], set())

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].commit_id, "init")


# ---------------------------------------------------------------------------
# enrich_commits (integration)
# ---------------------------------------------------------------------------

class TestEnrichCommits(unittest.TestCase):

    def test_regular_commits_enriched_normally(self):
        """Regular commits (1 parent) are enriched without expansion."""
        client = _make_client()
        client._get_commit_parents = MagicMock(return_value=["prev"])
        client.get_commit_changes = MagicMock(return_value=["file.py"])
        client.get_diff_text = MagicMock(return_value="diff text")

        commits = [_commit("abc"), _commit("def")]
        result = client.enrich_commits(commits)

        self.assertEqual(len(result), 2)
        for c in result:
            self.assertEqual(c.files_changed, ["file.py"])
            self.assertEqual(c.diff_text, "diff text")

    def test_merge_commit_expanded_before_enrichment(self):
        """Merge commits are expanded; only the expanded commits are enriched."""
        client = _make_client()

        def fake_parents(cid):
            return ["base", "head"] if cid == "merge" else ["prev"]

        client._get_commit_parents = MagicMock(side_effect=fake_parents)
        client._get_pr_inner_commits = MagicMock(
            return_value=[_commit("pr1"), _commit("pr2")]
        )
        client.get_commit_changes = MagicMock(return_value=[])
        client.get_diff_text = MagicMock(return_value="")

        result = client.enrich_commits([_commit("merge")])

        ids = {c.commit_id for c in result}
        self.assertEqual(ids, {"pr1", "pr2"})
        # merge commit itself must not appear
        self.assertNotIn("merge", ids)

    def test_progress_callback_uses_expanded_count(self):
        """on_progress total should reflect the expanded list, not the original."""
        client = _make_client()

        def fake_parents(cid):
            return ["base", "head"] if cid == "merge" else ["prev"]

        client._get_commit_parents = MagicMock(side_effect=fake_parents)
        client._get_pr_inner_commits = MagicMock(
            return_value=[_commit("pr1"), _commit("pr2"), _commit("pr3")]
        )
        client.get_commit_changes = MagicMock(return_value=[])
        client.get_diff_text = MagicMock(return_value="")

        totals: list[int] = []
        def progress(i, n, sha):
            totals.append(n)

        client.enrich_commits([_commit("merge")], on_progress=progress)

        # total should be 3 (expanded), not 1 (original)
        self.assertTrue(all(t == 3 for t in totals))

    def test_enrich_without_diff(self):
        """fetch_diff=False skips get_diff_text calls."""
        client = _make_client()
        client._get_commit_parents = MagicMock(return_value=["prev"])
        client.get_commit_changes = MagicMock(return_value=["a.py"])
        client.get_diff_text = MagicMock()

        client.enrich_commits([_commit("abc")], fetch_diff=False)

        client.get_diff_text.assert_not_called()

    def test_api_error_during_enrichment_sets_diff_message(self):
        """AzureAPIError during enrichment is caught and stored in diff_text."""
        client = _make_client()
        client._get_commit_parents = MagicMock(return_value=["prev"])
        client.get_commit_changes = MagicMock(side_effect=AzureAPIError("timeout"))
        client.get_diff_text = MagicMock()

        result = client.enrich_commits([_commit("abc")])

        self.assertIn("Error fetching diff", result[0].diff_text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
