"""The Dependabot sweep's pre-flight reasons and its result reporting.

The tally and the log lines were inline in the modal worker, so asserting
"a repo that failed to list is not counted as merged" meant driving the UI.
"""

from __future__ import annotations

import pytest

from repo_tui.app import MergeTally, pr_status_lines, repo_result_lines
from repo_tui.dependabot import MergeResult, RepoProgress, _preflight_reason
from repo_tui.models import PullRequest

# ---------- pre-flight ------------------------------------------------------------


@pytest.mark.parametrize(
    ("pr", "expected"),
    [
        ({"mergeable": "CONFLICTING"}, "has merge conflicts"),
        ({"statusCheckRollup": [{"state": "FAILURE"}]}, "CI checks failing"),
        ({"statusCheckRollup": [{"state": "PENDING"}]}, "CI checks still pending"),
        ({"mergeable": "MERGEABLE", "statusCheckRollup": [{"state": "SUCCESS"}]}, None),
        ({}, None),  # nothing known against it
    ],
)
def test_preflight_reason(pr: dict, expected: str | None) -> None:
    assert _preflight_reason(pr) == expected


def test_conflicts_outrank_failing_checks() -> None:
    """Both are blocking; the conflict is the one worth reporting."""
    pr = {"mergeable": "CONFLICTING", "statusCheckRollup": [{"state": "FAILURE"}]}
    assert _preflight_reason(pr) == "has merge conflicts"


# ---------- tally -----------------------------------------------------------------


def test_summary_omits_unreadable_when_none() -> None:
    summary = MergeTally(repos_with_prs=2, merged=3, failed=1).summary(total_repos=10)

    assert "scanned 10 repos" in summary
    assert "3 merged, 1 failed" in summary
    assert "unreadable" not in summary


def test_summary_reports_unreadable_repos() -> None:
    """An unreadable repo must not silently read as 'nothing to merge'."""
    summary = MergeTally(repos_with_prs=1, merged=0, failed=0, unreadable=2).summary(5)

    assert "2 unreadable" in summary


# ---------- per-repo log lines ----------------------------------------------------


def _log(progress: RepoProgress, tally: MergeTally) -> list[str]:
    return repo_result_lines(progress, tally)


def test_unreadable_repo_counts_as_unreadable_not_clean() -> None:
    tally = MergeTally()
    lines = _log(RepoProgress("api", "done", [], error="could not list PRs"), tally)

    assert tally.unreadable == 1
    assert tally.repos_with_prs == 0
    assert "could not list PRs" in lines[0]
    assert "no open Dependabot PRs" not in lines[0]


def test_repo_with_no_prs_is_logged_but_not_counted() -> None:
    tally = MergeTally()
    lines = _log(RepoProgress("api", "done", []), tally)

    assert tally.repos_with_prs == 0
    assert tally.unreadable == 0
    assert "no open Dependabot PRs" in lines[0]


def test_all_merged_says_all() -> None:
    tally = MergeTally()
    results = [MergeResult(1, "a", True, "merged"), MergeResult(2, "b", True, "merged")]
    lines = _log(RepoProgress("api", "done", results), tally)

    assert tally.merged == 2
    assert tally.failed == 0
    assert "All Dependabot PRs Merged (#1, #2)" in lines[0]


def test_partial_success_does_not_claim_all() -> None:
    tally = MergeTally()
    results = [
        MergeResult(1, "a", True, "merged"),
        MergeResult(2, "b", False, "has merge conflicts"),
    ]
    lines = _log(RepoProgress("api", "done", results), tally)

    assert tally.merged == 1
    assert tally.failed == 1
    joined = "\n".join(lines)
    assert "All Dependabot PRs Merged" not in joined
    assert "merged 1 Dependabot PR(s) (#1)" in joined
    assert "has merge conflicts" in joined


def test_total_failure_logs_no_success_line() -> None:
    tally = MergeTally()
    results = [MergeResult(1, "a", False, "CI checks failing")]
    lines = _log(RepoProgress("api", "done", results), tally)

    assert tally.merged == 0
    assert tally.failed == 1
    assert all("✓" not in line for line in lines)


# ---------- PR status block -------------------------------------------------------


def _pr(**kwargs) -> PullRequest:
    defaults = {"number": 1, "title": "t", "url": "u", "author": "a", "state": "OPEN"}
    return PullRequest(**{**defaults, **kwargs})


def test_pr_status_lines_order_and_content() -> None:
    lines = pr_status_lines(
        _pr(
            head_ref="feature/x",
            base_ref="main",
            review_decision="APPROVED",
            reviewers=["alice"],
            checks_status="SUCCESS",
            mergeable="MERGEABLE",
        )
    )

    assert len(lines) == 5
    assert "feature/x" in lines[0] and "main" in lines[0]
    assert "Approved" in lines[1]
    assert "alice" in lines[2]
    assert "Checks passing" in lines[3]
    assert "Ready to merge" in lines[4]


def test_pr_status_lines_empty_for_a_bare_pr() -> None:
    assert pr_status_lines(_pr()) == []


def test_pr_status_lines_redacts_branch_names_only() -> None:
    """Privacy mode masks branch names; the fixed labels stay readable."""
    lines = pr_status_lines(
        _pr(head_ref="secret-branch", base_ref="main", checks_status="FAILURE"),
        redact=lambda t: "*" * len(t),
    )

    assert "secret-branch" not in lines[0]
    assert "*" in lines[0]
    assert "Checks failing" in lines[1]


def test_unknown_status_values_render_nothing() -> None:
    lines = pr_status_lines(_pr(review_decision="WEIRD", checks_status="???", mergeable="UNKNOWN"))
    assert lines == []
