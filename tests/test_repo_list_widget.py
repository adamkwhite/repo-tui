"""Tests for the repo-list widget's special Dependabot action row."""

from __future__ import annotations

import pytest

from repo_tui.app import RepoOverviewApp
from repo_tui.models import RepoOverview
from repo_tui.widgets.repo_list import RepoListWidget


def _repo(name: str) -> RepoOverview:
    return RepoOverview(
        name=name,
        owner="test-owner",
        url=f"https://github.com/test-owner/{name}",
        open_issues_count=0,
        issues=[],
        sonar_status=None,
        pull_requests=[],
    )


@pytest.mark.asyncio
async def test_action_row_appears_first_and_is_not_a_repo():
    repos = [_repo("alpha"), _repo("beta")]
    app = RepoOverviewApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        widget = app.query_one("#repo-list", RepoListWidget)
        widget.set_repos(repos)
        await pilot.pause()

        first = widget.get_option_at_index(0)
        assert first is not None
        assert first.id == "action:dependabot-merge"

        # Highlight defaults to index 1 (first real repo), not the action row.
        assert widget.highlighted == 1
        assert widget.get_selected_repo() is not None
        assert widget.get_selected_special_action() is None


@pytest.mark.asyncio
async def test_action_row_detected_when_highlighted():
    repos = [_repo("alpha")]
    app = RepoOverviewApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        widget = app.query_one("#repo-list", RepoListWidget)
        widget.set_repos(repos)
        await pilot.pause()

        widget.highlighted = 0
        assert widget.get_selected_special_action() == "dependabot-merge"
        assert widget.get_selected_repo() is None
