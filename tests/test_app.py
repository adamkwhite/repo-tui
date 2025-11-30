"""Basic smoke tests for the app."""

from repo_tui.app import RepoOverviewApp


def test_app_can_instantiate():
    """Test that the app can be created without errors."""
    app = RepoOverviewApp()
    assert app is not None
    assert hasattr(app, "config")
    assert hasattr(app, "repos")
    assert app.view_mode == "list"


def test_app_can_instantiate_with_sonar():
    """Test that the app can be created with sonar check enabled."""
    app = RepoOverviewApp(check_sonar=True)
    assert app.check_sonar is True


def test_app_has_required_attributes():
    """Test that the app has all required attributes after init."""
    app = RepoOverviewApp()

    # Check that mouse_over is not set to a bool (it should be None or a widget)
    if hasattr(app, "mouse_over"):
        assert not isinstance(app.mouse_over, bool), (
            "mouse_over should not be a boolean, it should be a Widget or None"
        )

    # Check view mode is valid
    assert app.view_mode in ["list", "grid"]

    # Check repos is a list
    assert isinstance(app.repos, list)


def test_view_mode_switching():
    """Test view mode can be set to valid values."""
    app = RepoOverviewApp()
    app.view_mode = "grid"
    assert app.view_mode == "grid"
    app.view_mode = "list"
    assert app.view_mode == "list"
