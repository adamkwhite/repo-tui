"""Main TUI application."""

import asyncio

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, Center, VerticalScroll
from textual.widgets import Header, Footer, Static, LoadingIndicator
from textual.binding import Binding
from textual.screen import ModalScreen
from textual.message import Message

from .config import Config
from .data import fetch_all_repos
from .models import Issue
from .widgets.repo_list import RepoListWidget
from .widgets.issue_list import IssueListWidget
from .launcher import launch_claude


HELP_TEXT = """
[bold]Repo Overview TUI - Keyboard Shortcuts[/bold]

[cyan]Navigation[/cyan]
  j/k or ↑/↓    Move up/down
  Tab           Switch between panes
  Space         Expand/collapse repo issues

[cyan]Actions[/cyan]
  Enter         Launch Claude Code
  e             Show issue details
  o             Open in browser
  r             Refresh data
  /             Search (coming soon)
  q             Quit
  ?             Show this help

[dim]Press any key to close[/dim]
"""


class HelpScreen(ModalScreen):
    """Modal screen showing help."""

    BINDINGS = [Binding("escape", "dismiss", "Close")]

    def compose(self) -> ComposeResult:
        yield Static(HELP_TEXT, id="help-content")

    def on_key(self) -> None:
        """Dismiss on any key."""
        self.dismiss()


class LoadingScreen(ModalScreen):
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

    def __init__(self, message: str):
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


class IssueDetailScreen(ModalScreen):
    """Modal screen showing full issue details."""

    class IssueNavigated(Message):
        """Emitted when user navigates to a different issue."""
        def __init__(self, index: int):
            self.index = index
            super().__init__()

    BINDINGS = [
        Binding("escape", "close_modal", "Close"),
        Binding("e", "close_modal", "Close"),
    ]

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
            # Notify app to sync issue list widget
            self.post_message(self.IssueNavigated(new_index))

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

    def __init__(self, issue: Issue, repo_name: str = "", issue_list: list = None, current_index: int = 0):
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

    def _update_content(self) -> None:
        """Update all content for current issue."""
        issue = self.issue

        # Title
        title_text = f"[bold]{self.repo_name}[/bold] [cyan]#{issue.number}[/cyan] {self._escape(issue.title)}"
        self.query_one("#issue-title", Static).update(title_text)

        # Meta
        meta_parts = []
        if issue.assignee:
            meta_parts.append(f"Assignee: {issue.assignee}")
        meta_parts.append(f"State: {issue.state}")
        # Show position in list
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


class StatusBar(Static):
    """Status bar showing refresh time and counts."""

    def __init__(self):
        super().__init__("Loading...")
        self.add_class("status-bar")

    def update_stats(self, repo_count: int, issue_count: int, message: str = ""):
        """Update status bar with current stats."""
        if message:
            self.update(f"{message} | Repos: {repo_count} | Issues: {issue_count}")
        else:
            self.update(f"Repos: {repo_count} | Issues: {issue_count}")


class RepoOverviewApp(App):
    """Interactive TUI for GitHub repository overview."""

    ENABLE_COMMAND_PALETTE = False

    CSS = """
    #main-container {
        layout: horizontal;
        height: 1fr;
    }

    #repo-pane {
        width: 2fr;
        border: solid $primary;
        height: 100%;
    }

    #issue-pane {
        width: 3fr;
        border: solid $secondary;
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

    IssueListWidget {
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
        Binding("q", "quit", "Quit", priority=True),
        Binding("r", "refresh", "Refresh", priority=True),
        Binding("o", "open_browser", "Open", priority=True),
        Binding("e", "expand_issue", "Details", priority=True),
        Binding("question_mark", "help", "Help", priority=True),
        Binding("tab", "focus_next", "Switch Pane", show=False),
        Binding("space", "toggle_expand", "Expand", priority=True),
        Binding("enter", "launch", "Launch", priority=True),
        Binding("slash", "search", "Search", priority=True),
        Binding("j", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
        Binding("down", "cursor_down", "Down", show=False),
        Binding("up", "cursor_up", "Up", show=False),
    ]

    def __init__(self, check_sonar: bool = False):
        super().__init__()
        self.config = Config()
        self.repos = []
        self.check_sonar = check_sonar

    def compose(self) -> ComposeResult:
        """Create the UI layout."""
        yield Header()

        with Horizontal(id="main-container"):
            with Vertical(id="repo-pane"):
                yield Static("Repositories", classes="pane-title")
                yield RepoListWidget(id="repo-list")

            with Vertical(id="issue-pane"):
                yield Static("Issues", classes="pane-title")
                yield IssueListWidget(id="issue-list")

        yield StatusBar()
        yield Footer()

    async def on_mount(self) -> None:
        """Load data when app starts."""
        # Use call_later to show loading screen after mount completes
        self.call_later(self._initial_load)

    async def _initial_load(self) -> None:
        """Initial data load with loading screen."""
        loading_screen = LoadingScreen("Fetching repositories...")
        self.push_screen(loading_screen)

        # Small delay to let screen render
        await asyncio.sleep(0.1)

        try:
            await self._do_refresh(loading_screen)
        finally:
            self.pop_screen()

    async def _do_refresh(self, loading_screen: LoadingScreen = None) -> None:
        """Actually fetch and update data."""
        status_bar = self.query_one(StatusBar)

        async def progress_callback(current: int, total: int, repo_name: str) -> None:
            if loading_screen:
                loading_screen.update_message(f"Fetching {current}/{total}", repo_name)

        self.repos = await fetch_all_repos(
            self.config, self.check_sonar, progress_callback
        )

        # Update widgets
        repo_list = self.query_one("#repo-list", RepoListWidget)
        repo_list.set_repos(self.repos)

        # Update status bar
        total_issues = sum(r.open_issues_count for r in self.repos)
        status_bar.update_stats(len(self.repos), total_issues, "Ready")

    async def action_refresh(self) -> None:
        """Refresh repository data."""
        loading_screen = LoadingScreen("Refreshing...")
        self.push_screen(loading_screen)

        await asyncio.sleep(0.1)

        try:
            await self._do_refresh(loading_screen)
        finally:
            self.pop_screen()

    def on_repo_list_widget_repo_selected(self, event) -> None:
        """Handle repo selection - update issue list."""
        issue_list = self.query_one("#issue-list", IssueListWidget)
        issue_list.set_issues(event.repo.issues if event.repo else [])

    async def action_launch(self) -> None:
        """Launch Claude Code for selected repo/issue."""
        repo_list = self.query_one("#repo-list", RepoListWidget)
        issue_list = self.query_one("#issue-list", IssueListWidget)
        status_bar = self.query_one(StatusBar)

        selected_repo = repo_list.get_selected_repo()
        if not selected_repo:
            status_bar.update("No repo selected")
            return

        if not selected_repo.local_path:
            status_bar.update(f"Repo not found locally: ~/Code/{selected_repo.name}")
            return

        # Check if issue pane has focus and an issue is selected
        selected_issue = None
        if issue_list.has_focus:
            selected_issue = issue_list.get_selected_issue()

        # Show loading spinner
        if selected_issue:
            msg = f"Launching #{selected_issue.number}..."
        else:
            msg = f"Launching {selected_repo.name}..."
        loading_screen = LoadingScreen(msg)
        await self.push_screen(loading_screen)

        # Small delay to let spinner render, then launch
        await asyncio.sleep(0.1)
        result = launch_claude(selected_repo, selected_issue)

        # Wait a moment to show spinner, then dismiss
        await asyncio.sleep(1.5)
        self.pop_screen()

        status_bar.update(result)

    async def action_open_browser(self) -> None:
        """Open selected item in browser."""
        import subprocess

        repo_list = self.query_one("#repo-list", RepoListWidget)
        issue_list = self.query_one("#issue-list", IssueListWidget)

        url = None
        if issue_list.has_focus:
            issue = issue_list.get_selected_issue()
            if issue:
                url = issue.url
        else:
            repo = repo_list.get_selected_repo()
            if repo:
                url = repo.url

        if url:
            subprocess.Popen(["wslview", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    async def action_toggle_expand(self) -> None:
        """Toggle expand/collapse for selected repo."""
        repo_list = self.query_one("#repo-list", RepoListWidget)
        repo_list.toggle_expand()

    async def action_cursor_down(self) -> None:
        """Move cursor down in focused list."""
        focused = self.focused
        if isinstance(focused, (RepoListWidget, IssueListWidget)):
            focused.action_cursor_down()

    async def action_cursor_up(self) -> None:
        """Move cursor up in focused list."""
        focused = self.focused
        if isinstance(focused, (RepoListWidget, IssueListWidget)):
            focused.action_cursor_up()

    async def action_search(self) -> None:
        """Focus search input."""
        # TODO: Implement search modal
        pass

    async def action_expand_issue(self) -> None:
        """Show full issue details in a modal."""
        issue_list = self.query_one("#issue-list", IssueListWidget)
        repo_list = self.query_one("#repo-list", RepoListWidget)

        issue = None
        repo_name = ""

        if issue_list.has_focus:
            # Issue pane has focus - use its selection
            issue = issue_list.get_selected_issue()
            repo = repo_list.get_selected_repo()
            repo_name = repo.name if repo else ""
        else:
            # Repo pane has focus - check if inline issue is selected
            inline = repo_list.get_selected_inline_issue()
            if inline:
                repo, issue = inline
                repo_name = repo.name
                # Sync issue list to match
                for i, iss in enumerate(issue_list.issues):
                    if iss.number == issue.number:
                        issue_list._current_index = i
                        issue_list.highlighted = i
                        break
            else:
                # On a repo row - use first issue from issue list
                repo = repo_list.get_selected_repo()
                repo_name = repo.name if repo else ""
                if issue_list.issues:
                    issue_list._current_index = 0
                    issue_list.highlighted = 0
                    issue = issue_list.issues[0]

        if issue:
            self._current_repo_name = repo_name
            current_index = issue_list._current_index
            await self.push_screen(
                IssueDetailScreen(issue, repo_name, issue_list.issues, current_index),
                callback=self._on_issue_detail_dismiss
            )

    def _on_issue_detail_dismiss(self, result) -> None:
        """Sync issue list when modal is dismissed."""
        if result is not None and isinstance(result, int):
            issue_list = self.query_one("#issue-list", IssueListWidget)
            repo_list = self.query_one("#repo-list", RepoListWidget)

            # Sync issue list
            issue_list._current_index = result
            issue_list.highlighted = result

            # Sync repo list if expanded
            if issue_list.issues and result < len(issue_list.issues):
                issue = issue_list.issues[result]
                repo = repo_list.get_selected_repo()
                if repo and repo.name in repo_list.expanded:
                    target_id = f"issue:{repo.name}:{issue.number}"
                    repo_list._select_by_id(target_id)

    def on_issue_detail_screen_issue_navigated(self, event: IssueDetailScreen.IssueNavigated) -> None:
        """Sync issue list widget and repo list when user navigates in modal."""
        issue_list = self.query_one("#issue-list", IssueListWidget)
        repo_list = self.query_one("#repo-list", RepoListWidget)

        # Sync issue list
        issue_list._current_index = event.index
        issue_list.highlighted = event.index

        # Sync repo list if it has inline issues expanded
        if issue_list.issues and event.index < len(issue_list.issues):
            issue = issue_list.issues[event.index]
            repo = repo_list.get_selected_repo()
            if repo and repo.name in repo_list.expanded:
                # Find and select the inline issue in repo list
                target_id = f"issue:{repo.name}:{issue.number}"
                repo_list._select_by_id(target_id)

    async def action_help(self) -> None:
        """Show help modal."""
        await self.push_screen(HelpScreen())


def main():
    """Entry point for the repo-tui command."""
    app = RepoOverviewApp()
    app.run()


if __name__ == "__main__":
    main()
