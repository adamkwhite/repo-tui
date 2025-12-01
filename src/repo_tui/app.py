"""Main TUI application."""

from __future__ import annotations

import asyncio
import atexit
import subprocess
import sys
from typing import TYPE_CHECKING, Any

from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Footer, Header, LoadingIndicator, Static

from .config import Config
from .data import fetch_all_repos, fetch_single_repo
from .launcher import launch_claude
from .models import Issue, PullRequest
from .widgets.repo_grid import RepoGridWidget
from .widgets.repo_list import RepoListWidget

if TYPE_CHECKING:
    from .models import RepoOverview


def _cleanup_terminal():
    """Force terminal cleanup - runs via atexit."""
    try:
        sys.stdout.write("\x1b[?1000l")  # Disable mouse click tracking
        sys.stdout.write("\x1b[?1002l")  # Disable mouse drag tracking
        sys.stdout.write("\x1b[?1003l")  # Disable all mouse tracking
        sys.stdout.write("\x1b[?1006l")  # Disable SGR mouse mode
        sys.stdout.write("\x1b[?25h")  # Show cursor
        sys.stdout.flush()
    except Exception:
        pass


# Register cleanup to run when Python exits
atexit.register(_cleanup_terminal)


HELP_TEXT = """
[bold]Repo Overview TUI - Keyboard Shortcuts[/bold]

[cyan]Navigation[/cyan]
  j/k or ↑/↓    Move up/down
  Space         Expand/collapse repo issues
  1             Switch to list view
  2             Switch to grid view
  3             Switch to Jira view (if configured)

[cyan]Actions[/cyan]
  c             Launch Claude Code
  e             Show issue details
  o             Open in browser
  r             Refresh current repo
  R             Refresh all repos
  s             Check SonarCloud for current repo
  S             Toggle SonarCloud for all repos
  q             Quit
  ?             Show this help

[cyan]Status Indicators (colored dots)[/cyan]
  [red]●[/red]             Sonar ERROR or 5+ critical issues (bugs/security)
  [yellow]●[/yellow]             Sonar WARN, uncommitted changes, or 1-4 critical issues
  [blue]●[/blue]             Active PRs or work in progress
  [green]●[/green]             Clean (no issues or uncommitted work)

[dim]Critical labels: bug, security, breaking-change, ci-failure, priority-high, status-blocked[/dim]
[dim]Note: Terminal color schemes may render yellow as orange, blue as purple[/dim]
[dim]Press any key to close[/dim]
"""


class HelpScreen(ModalScreen[None]):
    """Modal screen showing help."""

    def compose(self) -> ComposeResult:
        yield Static(HELP_TEXT, id="help-content")

    def on_key(self, event: events.Key) -> None:
        """Dismiss on any key."""
        event.stop()
        self.dismiss()


class LoadingScreen(ModalScreen[None]):
    """Modal screen showing a loading spinner with custom message."""

    DEFAULT_CSS = """
    LoadingScreen {
        align: center middle;
    }

    #loading-container {
        width: 55;
        height: 9;
        background: $surface;
        border: solid $primary;
        padding: 1 2;
    }

    #loading-text {
        text-align: center;
        width: 100%;
    }

    #loading-repo {
        text-align: center;
        width: 100%;
        color: $text-muted;
    }

    #loading-spinner {
        width: 100%;
        height: 3;
    }
    """

    def __init__(self, message: str) -> None:
        super().__init__()
        self.message = message

    def compose(self) -> ComposeResult:
        with Vertical(id="loading-container"):
            yield Static(self.message, id="loading-text")
            yield Static("", id="loading-repo")
            yield LoadingIndicator(id="loading-spinner")

    def update_message(self, message: str, repo_name: str = "") -> None:
        """Update the loading message."""
        self.query_one("#loading-text", Static).update(message)
        self.query_one("#loading-repo", Static).update(repo_name)


class IssueDetailScreen(ModalScreen[int]):
    """Modal screen showing full issue details."""

    BINDINGS = [
        Binding("escape", "close_modal", "Close"),
        Binding("e", "close_modal", "Close"),
    ]

    DEFAULT_CSS = """
    IssueDetailScreen {
        align: center middle;
    }

    #issue-detail-container {
        width: 80%;
        height: 80%;
        max-width: 100;
        background: $surface;
        border: solid $primary;
        padding: 1 2;
    }

    #issue-header {
        height: auto;
        margin-bottom: 1;
    }

    #issue-title {
        text-style: bold;
        color: $text;
    }

    #issue-meta {
        color: $text-muted;
        height: auto;
    }

    #issue-labels {
        height: auto;
        margin-bottom: 1;
    }

    #issue-body-scroll {
        height: 1fr;
        border: solid $secondary;
        padding: 1;
    }

    #issue-body {
        width: 100%;
    }

    #issue-footer {
        dock: bottom;
        height: 1;
        color: $text-muted;
    }
    """

    def __init__(
        self,
        issue: Issue,
        repo_name: str = "",
        issue_list: list[Issue] | None = None,
        current_index: int = 0,
    ) -> None:
        super().__init__()
        self.issue = issue
        self.repo_name = repo_name
        self.issue_list = issue_list or []
        self.current_index = current_index

    def compose(self) -> ComposeResult:
        with Vertical(id="issue-detail-container"):
            with Vertical(id="issue-header"):
                yield Static("", id="issue-title")
                yield Static("", id="issue-meta")

            yield Static("", id="issue-labels")

            with VerticalScroll(id="issue-body-scroll"):
                yield Static("", id="issue-body")

            yield Static("[dim]j/k scroll | h/l prev/next | Esc close[/dim]", id="issue-footer")

    def on_mount(self) -> None:
        """Update content on mount."""
        self._update_content()

    def action_close_modal(self) -> None:
        """Close modal and return final index."""
        self.dismiss(result=self.current_index)

    def key_j(self) -> None:
        """Scroll down."""
        scroll = self.query_one("#issue-body-scroll", VerticalScroll)
        scroll.scroll_relative(y=3, animate=False)

    def key_k(self) -> None:
        """Scroll up."""
        scroll = self.query_one("#issue-body-scroll", VerticalScroll)
        scroll.scroll_relative(y=-3, animate=False)

    def key_down(self) -> None:
        """Scroll down."""
        scroll = self.query_one("#issue-body-scroll", VerticalScroll)
        scroll.scroll_relative(y=3, animate=False)

    def key_up(self) -> None:
        """Scroll up."""
        scroll = self.query_one("#issue-body-scroll", VerticalScroll)
        scroll.scroll_relative(y=-3, animate=False)

    def key_h(self) -> None:
        """Previous issue."""
        self._navigate(-1)

    def key_l(self) -> None:
        """Next issue."""
        self._navigate(1)

    def key_left(self) -> None:
        """Previous issue."""
        self._navigate(-1)

    def key_right(self) -> None:
        """Next issue."""
        self._navigate(1)

    def _navigate(self, direction: int) -> None:
        """Navigate to prev/next issue in place."""
        if not self.issue_list:
            return

        new_index = self.current_index + direction
        if 0 <= new_index < len(self.issue_list):
            self.current_index = new_index
            self.issue = self.issue_list[new_index]
            self._update_content()

    def _update_content(self) -> None:
        """Update all content for current issue."""
        issue = self.issue

        # Title
        title_text = (
            f"[bold]{self.repo_name}[/bold] "
            f"[cyan]#{issue.number}[/cyan] {self._escape(issue.title)}"
        )
        self.query_one("#issue-title", Static).update(title_text)

        # Meta
        meta_parts = []
        if issue.assignee:
            meta_parts.append(f"Assignee: {issue.assignee}")
        meta_parts.append(f"State: {issue.state}")
        if self.issue_list:
            meta_parts.append(f"({self.current_index + 1}/{len(self.issue_list)})")
        self.query_one("#issue-meta", Static).update(" | ".join(meta_parts))

        # Labels
        if issue.labels:
            labels_text = " ".join(f"[on blue] {label} [/on blue]" for label in issue.labels)
        else:
            labels_text = ""
        self.query_one("#issue-labels", Static).update(labels_text)

        # Body
        body = issue.body or "[dim]No description provided[/dim]"
        self.query_one("#issue-body", Static).update(self._escape(body))

        # Reset scroll position
        self.query_one("#issue-body-scroll", VerticalScroll).scroll_home()

    def _escape(self, text: str) -> str:
        """Escape Rich markup characters in text."""
        return text.replace("[", r"\[").replace("]", r"\]")


class PRDetailScreen(ModalScreen[int]):
    """Modal screen showing PR details."""

    BINDINGS = [
        Binding("escape", "close_modal", "Close"),
        Binding("e", "close_modal", "Close"),
    ]

    DEFAULT_CSS = """
    PRDetailScreen {
        align: center middle;
    }

    #pr-detail-container {
        width: 90%;
        height: 80%;
        max-width: 120;
        background: $surface;
        border: solid $primary;
        padding: 1 2;
    }

    #pr-header {
        height: auto;
        margin-bottom: 1;
    }

    #pr-title {
        text-style: bold;
        color: $text;
    }

    #pr-meta {
        color: $text-muted;
        height: auto;
    }

    #pr-status {
        height: auto;
        margin-bottom: 1;
    }

    #pr-labels {
        height: auto;
        margin-bottom: 1;
    }

    #pr-body-scroll {
        height: 1fr;
        border: solid $secondary;
        padding: 1;
        margin-bottom: 1;
    }

    #pr-body {
        width: 100%;
    }

    #pr-footer {
        dock: bottom;
        height: 1;
        color: $text-muted;
    }
    """

    def __init__(
        self,
        pr: PullRequest,
        repo_name: str = "",
        pr_list: list[PullRequest] | None = None,
        current_index: int = 0,
    ) -> None:
        super().__init__()
        self.pr = pr
        self.repo_name = repo_name
        self.pr_list = pr_list or []
        self.current_index = current_index

    def compose(self) -> ComposeResult:
        with Vertical(id="pr-detail-container"):
            with Vertical(id="pr-header"):
                yield Static("", id="pr-title")
                yield Static("", id="pr-meta")

            yield Static("", id="pr-status")
            yield Static("", id="pr-labels")

            with VerticalScroll(id="pr-body-scroll"):
                yield Static("", id="pr-body")

            yield Static("[dim]h/l prev/next | Esc close[/dim]", id="pr-footer")

    def on_mount(self) -> None:
        """Update content on mount."""
        self._update_content()

    def action_close_modal(self) -> None:
        """Close modal and return final index."""
        self.dismiss(result=self.current_index)

    def key_h(self) -> None:
        """Previous PR."""
        self._navigate(-1)

    def key_l(self) -> None:
        """Next PR."""
        self._navigate(1)

    def key_left(self) -> None:
        """Previous PR."""
        self._navigate(-1)

    def key_right(self) -> None:
        """Next PR."""
        self._navigate(1)

    def _navigate(self, direction: int) -> None:
        """Navigate to prev/next PR."""
        if not self.pr_list:
            return

        new_index = self.current_index + direction
        if 0 <= new_index < len(self.pr_list):
            self.current_index = new_index
            self.pr = self.pr_list[new_index]
            self._update_content()

    def _update_content(self) -> None:
        """Update all content for current PR."""
        pr = self.pr

        # Title
        draft_badge = "[yellow]DRAFT[/yellow] " if pr.draft else ""
        title_text = (
            f"[bold]{self.repo_name}[/bold] "
            f"[green]PR #{pr.number}[/green] {draft_badge}{self._escape(pr.title)}"
        )
        self.query_one("#pr-title", Static).update(title_text)

        # Meta - author, dates, navigation
        display_name = pr.author_name if pr.author_name else pr.author
        meta_parts = [f"by {display_name}"]
        if pr.created_at:
            # Simple date formatting (just the date part)
            created_date = pr.created_at.split("T")[0]
            meta_parts.append(f"created {created_date}")
        if pr.updated_at:
            updated_date = pr.updated_at.split("T")[0]
            meta_parts.append(f"updated {updated_date}")
        if self.pr_list:
            meta_parts.append(f"({self.current_index + 1}/{len(self.pr_list)})")
        self.query_one("#pr-meta", Static).update(" | ".join(meta_parts))

        # Status section - branches, review, checks, merge status
        status_parts = []

        # Branch info
        if pr.head_ref and pr.base_ref:
            status_parts.append(f"[cyan]{pr.head_ref}[/cyan] → [cyan]{pr.base_ref}[/cyan]")

        # Review decision
        if pr.review_decision == "APPROVED":
            status_parts.append("[green]✓ Approved[/green]")
        elif pr.review_decision == "CHANGES_REQUESTED":
            status_parts.append("[yellow]⚠ Changes requested[/yellow]")
        elif pr.review_decision == "REVIEW_REQUIRED":
            status_parts.append("[dim]Review required[/dim]")

        # Reviewers
        if pr.reviewers:
            reviewers_str = ", ".join(pr.reviewers)
            status_parts.append(f"[dim]Reviewers: {reviewers_str}[/dim]")

        # CI/CD checks
        if pr.checks_status == "SUCCESS":
            status_parts.append("[green]✓ Checks passing[/green]")
        elif pr.checks_status == "FAILURE":
            status_parts.append("[red]✗ Checks failing[/red]")
        elif pr.checks_status == "PENDING":
            status_parts.append("[yellow]⋯ Checks pending[/yellow]")

        # Merge status
        if pr.mergeable == "MERGEABLE":
            status_parts.append("[green]✓ Ready to merge[/green]")
        elif pr.mergeable == "CONFLICTING":
            status_parts.append("[red]✗ Has conflicts[/red]")

        self.query_one("#pr-status", Static).update("\n".join(status_parts) if status_parts else "")

        # Labels
        if pr.labels:
            labels_text = " ".join(f"[on blue] {label} [/on blue]" for label in pr.labels)
        else:
            labels_text = ""
        self.query_one("#pr-labels", Static).update(labels_text)

        # Body/description
        body_text = pr.body if pr.body else "[dim]No description provided[/dim]"
        self.query_one("#pr-body", Static).update(body_text)

    def _escape(self, text: str) -> str:
        """Escape Rich markup characters in text."""
        return text.replace("[", r"\[").replace("]", r"\]")


class StatusBar(Static):
    """Status bar showing refresh time and counts."""

    def __init__(self) -> None:
        super().__init__("Loading...")
        self.add_class("status-bar")

    def update_stats(self, repo_count: int, issue_count: int, message: str = "") -> None:
        """Update status bar with current stats."""
        if message:
            self.update(f"{message} | Repos: {repo_count} | Issues: {issue_count}")
        else:
            self.update(f"Repos: {repo_count} | Issues: {issue_count}")


class RepoOverviewApp(App[None]):
    """Interactive TUI for GitHub repository overview."""

    ENABLE_COMMAND_PALETTE = False

    CSS = """
    #main-container {
        height: 1fr;
    }

    #repo-pane {
        border: solid $primary;
        height: 100%;
    }

    .status-bar {
        dock: bottom;
        height: 1;
        background: $surface;
        color: $text-muted;
        padding: 0 1;
    }

    RepoListWidget {
        height: 1fr;
    }

    .pane-title {
        dock: top;
        height: 1;
        background: $primary-background;
        color: $text;
        text-style: bold;
        padding: 0 1;
    }

    HelpScreen {
        align: center middle;
    }

    #help-content {
        width: 50;
        height: auto;
        padding: 1 2;
        background: $surface;
        border: solid $primary;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh_repo", "Refresh"),
        Binding("R", "refresh_all", "Refresh All"),
        Binding("o", "open_browser", "Open"),
        Binding("e", "expand_issue", "Details"),
        Binding("c", "launch", "Claude"),
        Binding("s", "sonar_repo", "Sonar"),
        Binding("S", "sonar_all", "Sonar All"),
        Binding("question_mark", "help", "Help"),
        Binding("space", "toggle_expand", "Expand"),
        Binding("1", "switch_view_list", "List", show=False),
        Binding("2", "switch_view_grid", "Grid", show=False),
        Binding("j", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
        Binding("h", "cursor_left", "Left", show=False),
        Binding("l", "cursor_right", "Right", show=False),
        Binding("down", "cursor_down", "Down", show=False),
        Binding("up", "cursor_up", "Up", show=False),
        Binding("left", "cursor_left", "Left", show=False),
        Binding("right", "cursor_right", "Right", show=False),
    ]

    def __init__(self, check_sonar: bool = False) -> None:
        super().__init__()
        self.config = Config()
        self.repos: list[RepoOverview] = []
        self.check_sonar = check_sonar
        self.view_mode = "list"  # "list" or "grid"

    def compose(self) -> ComposeResult:
        """Create the UI layout."""
        yield Header()

        with Vertical(id="main-container"), Vertical(id="repo-pane"):
            yield Static("Repositories", classes="pane-title")
            if self.view_mode == "list":
                yield RepoListWidget(id="repo-list")
            else:  # grid
                yield RepoGridWidget(id="repo-grid")

        yield StatusBar()
        yield Footer()

    async def on_mount(self) -> None:
        """Load data when app starts."""
        self.call_later(self._initial_load)

    async def _on_exit_app(self) -> None:
        """Called when the app is about to exit - disable mouse before Textual cleanup."""
        try:
            # Force disable mouse tracking before Textual's cleanup
            sys.stdout.write("\x1b[?1000l")
            sys.stdout.write("\x1b[?1002l")
            sys.stdout.write("\x1b[?1003l")
            sys.stdout.write("\x1b[?1006l")
            sys.stdout.flush()
        except Exception:
            pass
        await super()._on_exit_app()

    async def _shutdown(self) -> None:
        """Override shutdown to ensure mouse is disabled."""
        try:
            # Disable mouse one more time during shutdown
            sys.stdout.write("\x1b[?1000l")
            sys.stdout.write("\x1b[?1002l")
            sys.stdout.write("\x1b[?1003l")
            sys.stdout.write("\x1b[?1006l")
            sys.stdout.flush()
        except Exception:
            pass
        await super()._shutdown()

    async def _initial_load(self) -> None:
        """Initial data load with loading screen."""
        loading_screen = LoadingScreen("Fetching repositories...")
        self.push_screen(loading_screen)

        await asyncio.sleep(0.1)

        try:
            await self._do_refresh(loading_screen)
        finally:
            self.pop_screen()

    async def _do_refresh(self, loading_screen: LoadingScreen | None = None) -> None:
        """Actually fetch and update data."""
        status_bar = self.query_one(StatusBar)

        async def progress_callback(current: int, total: int, repo_name: str) -> None:
            if loading_screen:
                loading_screen.update_message(f"Fetching {current}/{total}", repo_name)

        # Save existing sonar status before refresh
        old_sonar_status: dict[str, tuple[Any, bool]] = {}
        for repo in self.repos:
            if repo.sonar_checked:
                old_sonar_status[repo.name] = (repo.sonar_status, repo.sonar_checked)

        self.repos = await fetch_all_repos(self.config, self.check_sonar, progress_callback)

        # Restore sonar status to refreshed repos
        for repo in self.repos:
            if repo.name in old_sonar_status:
                repo.sonar_status, repo.sonar_checked = old_sonar_status[repo.name]

        repo_list = self.query_one("#repo-list", RepoListWidget)
        repo_list.set_repos(self.repos)

        total_issues = sum(r.open_issues_count for r in self.repos)
        sonar_indicator = " [SonarCloud ON]" if self.check_sonar else ""
        status_bar.update_stats(len(self.repos), total_issues, f"Ready{sonar_indicator}")

    def _get_current_widget(self):
        """Get the current view widget (list or grid)."""
        try:
            if self.view_mode == "list":
                return self.query_one("#repo-list", RepoListWidget)
            else:
                return self.query_one("#repo-grid", RepoGridWidget)
        except Exception:
            # Widget might not exist during transition
            return None

    async def action_switch_view_list(self) -> None:
        """Switch to list view."""
        if self.view_mode != "list":
            # Switch view mode
            self.view_mode = "list"
            await self.recompose()

            # Restore data
            new_widget = self._get_current_widget()
            if new_widget:
                new_widget.set_repos(self.repos)

    async def action_switch_view_grid(self) -> None:
        """Switch to grid view."""
        if self.view_mode != "grid":
            # Switch view mode
            self.view_mode = "grid"
            await self.recompose()

            # Restore data
            new_widget = self._get_current_widget()
            if new_widget:
                new_widget.set_repos(self.repos)

    async def action_refresh_repo(self) -> None:
        """Refresh the currently selected repository."""
        current_widget = self._get_current_widget()
        status_bar = self.query_one(StatusBar)

        if not current_widget:
            return

        selected_repo = current_widget.get_selected_repo()
        if not selected_repo:
            status_bar.update_stats(
                len(self.repos), sum(r.open_issues_count for r in self.repos), "No repo selected"
            )
            return

        loading_screen = LoadingScreen(f"Refreshing {selected_repo.name}...")
        self.push_screen(loading_screen)

        await asyncio.sleep(0.1)

        try:
            updated_repo = await fetch_single_repo(
                self.config,
                selected_repo.owner,
                selected_repo.name,
                self.check_sonar,
            )

            # Replace the repo in our list
            for i, repo in enumerate(self.repos):
                if repo.name == selected_repo.name:
                    self.repos[i] = updated_repo
                    break

            current_widget.set_repos(self.repos)

            # Re-select the same repo (only works for list view)
            if self.view_mode == "list":
                current_widget._select_by_id(f"repo:{selected_repo.name}")

            total_issues = sum(r.open_issues_count for r in self.repos)
            sonar_indicator = " [SonarCloud ON]" if self.check_sonar else ""
            status_bar.update_stats(
                len(self.repos), total_issues, f"Refreshed {selected_repo.name}{sonar_indicator}"
            )
        finally:
            self.pop_screen()

    async def action_refresh_all(self) -> None:
        """Refresh all repository data."""
        loading_screen = LoadingScreen("Refreshing all...")
        self.push_screen(loading_screen)

        await asyncio.sleep(0.1)

        try:
            await self._do_refresh(loading_screen)
        finally:
            self.pop_screen()

    async def action_sonar_repo(self) -> None:
        """Fetch SonarCloud status for the currently selected repo."""
        current_widget = self._get_current_widget()
        status_bar = self.query_one(StatusBar)

        selected_repo = current_widget.get_selected_repo()
        if not selected_repo:
            status_bar.update_stats(
                len(self.repos), sum(r.open_issues_count for r in self.repos), "No repo selected"
            )
            return

        loading_screen = LoadingScreen(f"Checking Sonar for {selected_repo.name}...")
        self.push_screen(loading_screen)

        await asyncio.sleep(0.1)

        try:
            updated_repo = await fetch_single_repo(
                self.config,
                selected_repo.owner,
                selected_repo.name,
                check_sonar=True,
            )

            # Replace the repo in our list
            for i, repo in enumerate(self.repos):
                if repo.name == selected_repo.name:
                    self.repos[i] = updated_repo
                    break

            current_widget.set_repos(self.repos)
            if self.view_mode == "list":
                current_widget._select_by_id(f"repo:{selected_repo.name}")

            total_issues = sum(r.open_issues_count for r in self.repos)
            status_bar.update_stats(
                len(self.repos), total_issues, f"Sonar checked: {selected_repo.name}"
            )
        finally:
            self.pop_screen()

    async def action_sonar_all(self) -> None:
        """Check SonarCloud status for all repos."""
        loading_screen = LoadingScreen("Checking Sonar for all repos...")
        self.push_screen(loading_screen)

        await asyncio.sleep(0.1)

        try:
            from .data import SonarCloudClient

            sonar = SonarCloudClient(self.config)

            total = len(self.repos)
            for i, repo in enumerate(self.repos):
                loading_screen.update_message(f"Checking {i + 1}/{total}", repo.name)

                # Try to find sonar project
                project_keys = sonar.guess_project_key(repo.owner, repo.name)
                for project_key in project_keys:
                    sonar_status = await sonar.get_project_status(project_key)
                    if sonar_status:
                        repo.sonar_status = sonar_status
                        repo.sonar_checked = True
                        break
                else:
                    # No sonar project found
                    repo.sonar_checked = True
                    repo.sonar_status = None

            # Update the display
            current_widget = self._get_current_widget()
            if current_widget:
                current_widget.set_repos(self.repos)

            status_bar = self.query_one(StatusBar)
            total_issues = sum(r.open_issues_count for r in self.repos)
            status_bar.update_stats(len(self.repos), total_issues, "Sonar checked all repos")
        finally:
            self.pop_screen()

    async def action_launch(self) -> None:
        """Launch Claude Code for selected repo/issue/PR."""
        current_widget = self._get_current_widget()
        status_bar = self.query_one(StatusBar)

        selected_repo = current_widget.get_selected_repo()
        if not selected_repo:
            status_bar.update("No repo selected")
            return

        if not selected_repo.local_path:
            status_bar.update(f"Repo not found locally: ~/Code/{selected_repo.name}")
            return

        # Check if an inline PR is selected
        pr_inline = current_widget.get_selected_inline_pr()
        selected_pr = pr_inline[1] if pr_inline else None

        # Check if an inline issue is selected
        issue_inline = current_widget.get_selected_inline_issue()
        selected_issue = issue_inline[1] if issue_inline else None

        msg = ""
        if selected_pr:
            msg = f"Launching PR #{selected_pr.number}..."
        elif selected_issue:
            msg = f"Launching #{selected_issue.number}..."
        else:
            msg = f"Launching {selected_repo.name}..."

        loading_screen = LoadingScreen(msg)
        await self.push_screen(loading_screen)

        await asyncio.sleep(0.1)
        result = launch_claude(selected_repo, self.config, selected_issue, selected_pr)

        await asyncio.sleep(1.5)
        self.pop_screen()

        status_bar.update(result)

    async def action_open_browser(self) -> None:
        """Open selected item in browser."""
        current_widget = self._get_current_widget()
        status_bar = self.query_one(StatusBar)

        url = None
        # Check for inline PR first
        inline_pr = current_widget.get_selected_inline_pr()
        if inline_pr:
            url = inline_pr[1].url
        else:
            # Check for inline issue
            inline_issue = current_widget.get_selected_inline_issue()
            if inline_issue:
                url = inline_issue[1].url
            else:
                # Fall back to repo URL
                repo = current_widget.get_selected_repo()
                if repo:
                    url = repo.url

        if url:
            try:
                # Use cmd.exe to open URL in Windows default browser from WSL
                subprocess.Popen(
                    ["cmd.exe", "/c", "start", url],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                status_bar.update("Opening in browser...")
            except Exception as e:
                status_bar.update(f"Error opening browser: {e}")

    async def action_toggle_expand(self) -> None:
        """Toggle expand/collapse for selected repo (list view only)."""
        if self.view_mode == "list":
            repo_list = self.query_one("#repo-list", RepoListWidget)
            repo_list.toggle_expand()

    async def action_cursor_down(self) -> None:
        """Move cursor down in current widget."""
        current_widget = self._get_current_widget()
        if current_widget:
            current_widget.action_cursor_down()

    async def action_cursor_up(self) -> None:
        """Move cursor up in current widget."""
        current_widget = self._get_current_widget()
        if current_widget:
            current_widget.action_cursor_up()

    async def action_cursor_left(self) -> None:
        """Move cursor left in current widget (grid only)."""
        if self.view_mode == "grid":
            current_widget = self._get_current_widget()
            if current_widget:
                current_widget.action_cursor_left()

    async def action_cursor_right(self) -> None:
        """Move cursor right in current widget (grid only)."""
        if self.view_mode == "grid":
            current_widget = self._get_current_widget()
            if current_widget:
                current_widget.action_cursor_right()

    async def action_expand_issue(self) -> None:
        """Show full issue or PR details in a modal."""
        current_widget = self._get_current_widget()

        # Check if PR is selected
        pr_inline = current_widget.get_selected_inline_pr()
        if pr_inline:
            repo, pr = pr_inline
            pr_list = repo.pull_requests or []
            current_index = next(
                (i for i, p in enumerate(pr_list) if p.number == pr.number),
                0,
            )
            await self.push_screen(
                PRDetailScreen(pr, repo.name, pr_list, current_index),
                callback=self._on_pr_detail_dismiss,
            )
            return

        # Check if issue is selected
        issue_inline = current_widget.get_selected_inline_issue()
        if issue_inline:
            repo, issue = issue_inline
            issue_list = repo.issues
            current_index = next(
                (i for i, iss in enumerate(issue_list) if iss.number == issue.number),
                0,
            )
            await self.push_screen(
                IssueDetailScreen(issue, repo.name, issue_list, current_index),
                callback=self._on_issue_detail_dismiss,
            )
            return

        # On a repo row - expand to show PRs/issues first, or show first PR/issue
        repo = current_widget.get_selected_repo()
        if repo:
            # List view: check if expanded
            if self.view_mode == "list" and repo.name not in current_widget.expanded:
                current_widget.toggle_expand()
            else:
                # Already expanded, show first PR or issue
                if repo.pull_requests:
                    await self.push_screen(
                        PRDetailScreen(repo.pull_requests[0], repo.name, repo.pull_requests, 0),
                        callback=self._on_pr_detail_dismiss,
                    )
                elif repo.issues:
                    await self.push_screen(
                        IssueDetailScreen(repo.issues[0], repo.name, repo.issues, 0),
                        callback=self._on_issue_detail_dismiss,
                    )

    def _on_issue_detail_dismiss(self, result: int | None) -> None:
        """Sync widget when modal is dismissed (list view only)."""
        if result is not None and self.view_mode == "list":
            repo_list = self.query_one("#repo-list", RepoListWidget)
            repo = repo_list.get_selected_repo()
            if repo and repo.name in repo_list.expanded and result < len(repo.issues):
                issue = repo.issues[result]
                target_id = f"issue:{repo.name}:{issue.number}"
                repo_list._select_by_id(target_id)

    def _on_pr_detail_dismiss(self, result: int | None) -> None:
        """Sync widget when PR modal is dismissed (list view only)."""
        if result is not None and self.view_mode == "list":
            repo_list = self.query_one("#repo-list", RepoListWidget)
            repo = repo_list.get_selected_repo()
            if (
                repo
                and repo.name in repo_list.expanded
                and repo.pull_requests
                and result < len(repo.pull_requests)
            ):
                pr = repo.pull_requests[result]
                target_id = f"pr:{repo.name}:{pr.number}"
                repo_list._select_by_id(target_id)

    async def action_help(self) -> None:
        """Show help modal."""
        await self.push_screen(HelpScreen())


def main() -> None:
    """Entry point for the repo-tui command."""
    import argparse

    parser = argparse.ArgumentParser(description="Terminal UI for GitHub repository overview")
    parser.add_argument(
        "-s", "--sonar", action="store_true", help="Check SonarCloud/SonarQube status on startup"
    )
    args = parser.parse_args()

    app = RepoOverviewApp(check_sonar=args.sonar)
    app.run()


if __name__ == "__main__":
    main()
