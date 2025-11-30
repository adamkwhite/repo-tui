"""Integration tests for the repo-tui app using Textual's Pilot API."""

from unittest.mock import AsyncMock, patch

import pytest

from repo_tui.app import RepoOverviewApp
from repo_tui.models import RepoOverview


@pytest.fixture
def sample_repos():
    """Create sample repos for testing."""
    return [
        RepoOverview(
            name="test-repo-1",
            owner="test-owner",
            url="https://github.com/test-owner/test-repo-1",
            open_issues_count=5,
            issues=[],
            sonar_status=None,
            local_path=None,
            sonar_checked=False,
            pull_requests=[],
            details_loaded=True,
            has_uncommitted_changes=False,
            current_branch="main",
        ),
        RepoOverview(
            name="test-repo-2",
            owner="test-owner",
            url="https://github.com/test-owner/test-repo-2",
            open_issues_count=3,
            issues=[],
            sonar_status=None,
            local_path=None,
            sonar_checked=False,
            pull_requests=[],
            details_loaded=True,
            has_uncommitted_changes=True,
            current_branch="feature/test",
        ),
    ]


@pytest.mark.asyncio
async def test_app_starts_in_list_view():
    """Test that the app starts successfully in list view."""
    app = RepoOverviewApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.view_mode == "list"


@pytest.mark.asyncio
async def test_switch_to_grid_view(sample_repos):
    """Test switching from list view to grid view."""
    app = RepoOverviewApp()
    app.repos = sample_repos

    async with app.run_test() as pilot:
        await pilot.pause()

        # Start in list view
        assert app.view_mode == "list"

        # Switch to grid view by pressing '2'
        await pilot.press("2")
        await pilot.pause()

        # Should now be in grid view
        assert app.view_mode == "grid"


@pytest.mark.asyncio
async def test_switch_back_to_list_view(sample_repos):
    """Test switching from grid view back to list view."""
    app = RepoOverviewApp()
    app.repos = sample_repos

    async with app.run_test() as pilot:
        await pilot.pause()

        # Switch to grid
        await pilot.press("2")
        await pilot.pause()
        assert app.view_mode == "grid"

        # Switch back to list
        await pilot.press("1")
        await pilot.pause()
        assert app.view_mode == "list"


@pytest.mark.asyncio
async def test_grid_view_shows_repos(sample_repos):
    """Test that grid view displays repositories after switching."""
    # Mock the data fetching to prevent real API calls
    with patch('repo_tui.app.fetch_all_repos', new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = sample_repos

        app = RepoOverviewApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            # Manually set repos for testing (simulating after load)
            app.repos = sample_repos
            current_widget = app._get_current_widget()
            if current_widget:
                current_widget.set_repos(sample_repos)

            # Switch to grid view
            await pilot.press("2")
            await pilot.pause()

            # Grid widget should exist
            try:
                grid_widget = app.query_one("#repo-grid")
                assert grid_widget is not None

                # Should have repos
                assert hasattr(grid_widget, 'repos')
                assert len(grid_widget.repos) == 2
            except Exception as e:
                pytest.fail(f"Grid widget not found or doesn't have repos: {e}")


@pytest.mark.asyncio
async def test_quit_with_q_key():
    """Test that pressing 'q' exits the app."""
    app = RepoOverviewApp()

    async with app.run_test() as pilot:
        await pilot.pause()

        # Press 'q' to quit
        await pilot.press("q")
        await pilot.pause()

        # App should exit (run_test context will handle this)
        # If we get here without hanging, the test passes


@pytest.mark.asyncio
async def test_app_does_not_set_mouse_over_to_bool():
    """Test that mouse_over is never set to a boolean value."""
    app = RepoOverviewApp()

    async with app.run_test() as pilot:
        await pilot.pause()

        # Check initial state
        if hasattr(app, 'mouse_over'):
            assert not isinstance(app.mouse_over, bool), \
                "mouse_over should not be a boolean, it should be a Widget or None"

        # Try switching views and check again
        await pilot.press("2")
        await pilot.pause()

        if hasattr(app, 'mouse_over'):
            assert not isinstance(app.mouse_over, bool), \
                "mouse_over should not be a boolean after view switch"


@pytest.mark.asyncio
async def test_view_mode_persistence_during_recompose(sample_repos):
    """Test that repos are preserved when switching views."""
    # Mock the data fetching to prevent real API calls
    with patch('repo_tui.app.fetch_all_repos', new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = sample_repos

        app = RepoOverviewApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            # Manually set repos for testing
            app.repos = sample_repos
            current_widget = app._get_current_widget()
            if current_widget:
                current_widget.set_repos(sample_repos)

            # Check initial repos
            initial_repo_count = len(app.repos)
            assert initial_repo_count == 2

            # Switch to grid and back
            await pilot.press("2")
            await pilot.pause()
            await pilot.press("1")
            await pilot.pause()

            # Repos should still be there
            assert len(app.repos) == initial_repo_count
            assert app.repos[0].name == "test-repo-1"
            assert app.repos[1].name == "test-repo-2"
