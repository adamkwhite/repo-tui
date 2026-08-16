"""Unit tests for the Dependabot bulk-merger."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from repo_tui.data import summarize_checks
from repo_tui.dependabot import (
    _is_dependabot_author,
    _shorten_reason,
    merge_all_dependabot_prs,
)
from repo_tui.models import PullRequest, RepoOverview


def _make_repo(name: str, prs: list[PullRequest] | None = None) -> RepoOverview:
    return RepoOverview(
        name=name,
        owner="test-owner",
        url=f"https://github.com/test-owner/{name}",
        open_issues_count=0,
        issues=[],
        sonar_status=None,
        pull_requests=prs,
    )


def _dependabot_pr(number: int = 1) -> PullRequest:
    return PullRequest(
        number=number,
        title=f"Bump something to {number}.0.0",
        url=f"https://github.com/test-owner/x/pull/{number}",
        author="dependabot[bot]",
        state="OPEN",
    )


def test_is_dependabot_author_variants():
    assert _is_dependabot_author("dependabot[bot]")
    assert _is_dependabot_author("Dependabot")
    assert _is_dependabot_author("app/dependabot")
    assert not _is_dependabot_author("renovate[bot]")
    assert not _is_dependabot_author("")
    assert not _is_dependabot_author(None)


def test_summarize_checks_handles_dict_and_list():
    passing_dict = {"contexts": [{"conclusion": "SUCCESS"}, {"state": "success"}]}
    assert summarize_checks(passing_dict) == "SUCCESS"

    failing_list = [{"state": "FAILURE"}, {"state": "SUCCESS"}]
    assert summarize_checks(failing_list) == "FAILURE"

    pending = [{"state": "PENDING"}, {"state": "SUCCESS"}]
    assert summarize_checks(pending) == "PENDING"

    assert summarize_checks({}) is None
    assert summarize_checks([]) is None
    assert summarize_checks(None) is None


def test_shorten_reason_known_patterns():
    assert _shorten_reason("Pull request is not mergeable", 1) == "merge conflicts"
    assert (
        _shorten_reason("required status check 'lint' is failing", 1) == "required checks failing"
    )
    assert _shorten_reason("review is required before merging", 1) == "review required"
    assert (
        _shorten_reason("blocked by branch protection rules", 1) == "blocked by branch protection"
    )
    # Unknown message falls back to the first line
    assert _shorten_reason("something totally weird happened", 1) == (
        "something totally weird happened"
    )
    assert _shorten_reason("", 7) == "gh merge exited 7"


@pytest.mark.asyncio
async def test_merger_emits_empty_done_for_repos_without_dependabot_prs():
    """Every repo should emit a done event so the modal can log it was checked."""
    repos = [_make_repo("no-deps", prs=[])]
    progress = [p async for p in merge_all_dependabot_prs(repos)]
    # Scanning, then done with empty results (nothing to merge, but logged).
    assert [p.phase for p in progress] == ["scanning", "done"]
    done = progress[1]
    assert done.repo_name == "no-deps"
    assert done.results == []


@pytest.mark.asyncio
async def test_merger_emits_empty_done_when_live_query_returns_nothing():
    """Repo had cached Dependabot PRs but live query finds none (already merged)."""
    repos = [_make_repo("stale-cache", prs=[_dependabot_pr(1)])]

    with patch(
        "repo_tui.dependabot._list_dependabot_prs",
        new=AsyncMock(return_value=[]),
    ):
        progress = [p async for p in merge_all_dependabot_prs(repos)]

    done = next(p for p in progress if p.phase == "done")
    assert done.repo_name == "stale-cache"
    assert done.results == []


@pytest.mark.asyncio
async def test_merger_reports_merge_success():
    repos = [_make_repo("has-deps", prs=[_dependabot_pr(1)])]

    live_prs = [
        {
            "number": 1,
            "title": "Bump x to 2.0.0",
            "mergeable": "MERGEABLE",
            "statusCheckRollup": [{"state": "SUCCESS"}],
        }
    ]

    with (
        patch(
            "repo_tui.dependabot._list_dependabot_prs",
            new=AsyncMock(return_value=live_prs),
        ),
        patch(
            "repo_tui.dependabot._merge_pr",
            new=AsyncMock(return_value=(True, "merged")),
        ),
    ):
        progress = [p async for p in merge_all_dependabot_prs(repos)]

    done_events = [p for p in progress if p.phase == "done"]
    assert len(done_events) == 1
    assert done_events[0].repo_name == "has-deps"
    assert len(done_events[0].results) == 1
    assert done_events[0].results[0].success is True


@pytest.mark.asyncio
async def test_merger_preflight_blocks_on_conflicts_and_failing_ci():
    repos = [_make_repo("has-deps", prs=[_dependabot_pr(1), _dependabot_pr(2)])]

    live_prs = [
        {
            "number": 1,
            "title": "conflict PR",
            "mergeable": "CONFLICTING",
            "statusCheckRollup": [{"state": "SUCCESS"}],
        },
        {
            "number": 2,
            "title": "ci-failing PR",
            "mergeable": "MERGEABLE",
            "statusCheckRollup": [{"state": "FAILURE"}],
        },
    ]

    merge_mock = AsyncMock(return_value=(True, "merged"))
    with (
        patch(
            "repo_tui.dependabot._list_dependabot_prs",
            new=AsyncMock(return_value=live_prs),
        ),
        patch("repo_tui.dependabot._merge_pr", new=merge_mock),
    ):
        progress = [p async for p in merge_all_dependabot_prs(repos)]

    # No actual merge call should happen — both PRs blocked in pre-flight.
    merge_mock.assert_not_called()

    done = next(p for p in progress if p.phase == "done")
    assert len(done.results) == 2
    reasons = {r.pr_number: r.reason for r in done.results}
    assert reasons[1] == "has merge conflicts"
    assert reasons[2] == "CI checks failing"
    assert all(r.success is False for r in done.results)
