"""Tests for the repo-list widget's special Dependabot action row."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from repo_tui.app import DependabotMergeScreen, RepoOverviewApp
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


@pytest.mark.asyncio
async def test_dependabot_modal_copy_action_strips_markup():
    """Pressing y on the modal copies plaintext (no Rich markup) to clipboard."""
    app = RepoOverviewApp()
    async with app.run_test() as pilot:
        await pilot.pause()

        screen = DependabotMergeScreen(repos=[])
        await app.push_screen(screen)
        await pilot.pause()

        # Inject log lines with markup so we can verify it's stripped.
        screen.log_lines = [
            "[green]✓[/green] alpha All Dependabot PRs Merged (#1, #2)",
            "[red]✗[/red] beta PR #3 unable to merge because of merge conflicts",
        ]

        fake_clipboard = MagicMock()
        app.copy_to_clipboard = fake_clipboard  # type: ignore[method-assign]

        screen.action_copy_log()

        fake_clipboard.assert_called_once()
        copied = fake_clipboard.call_args[0][0]
        assert "[green]" not in copied
        assert "[/green]" not in copied
        assert "✓ alpha All Dependabot PRs Merged (#1, #2)" in copied
        assert "✗ beta PR #3 unable to merge because of merge conflicts" in copied


@pytest.mark.asyncio
async def test_dependabot_modal_copy_skips_when_empty():
    """Copy action is a no-op when the log is empty (nothing to paste)."""
    app = RepoOverviewApp()
    async with app.run_test() as pilot:
        await pilot.pause()

        screen = DependabotMergeScreen(repos=[])
        await app.push_screen(screen)
        await pilot.pause()

        # Force an empty log — simulates the case before any results stream in.
        screen.log_lines = []

        fake_clipboard = MagicMock()
        app.copy_to_clipboard = fake_clipboard  # type: ignore[method-assign]

        screen.action_copy_log()

        fake_clipboard.assert_not_called()
