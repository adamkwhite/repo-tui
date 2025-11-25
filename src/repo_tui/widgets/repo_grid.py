"""Grid view widget for repository overview."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.containers import Grid, VerticalScroll
from textual.message import Message
from textual.widgets import Static

if TYPE_CHECKING:
    from ..models import RepoOverview


class RepoCard(Static):
    """A single repository card in the grid."""

    def __init__(self, repo: RepoOverview) -> None:
        super().__init__()
        self.repo = repo
        self.add_class("repo-card")
        self.can_focus = True

    def render(self) -> str:
        """Render the card content."""
        repo = self.repo

        # Build counts
        issue_count = repo.open_issues_count
        pr_count = len(repo.pull_requests) if repo.pull_requests else 0

        counts_parts = []
        if issue_count > 0:
            counts_parts.append(f"{issue_count} issues")
        if pr_count > 0:
            counts_parts.append(f"{pr_count} PRs")
        counts = ", ".join(counts_parts) if counts_parts else "No issues or PRs"

        # Git status
        git_status = ""
        if repo.local_path:
            if repo.has_uncommitted_changes:
                git_status = f"[yellow]✱ uncommitted[/yellow]"
            elif repo.current_branch:
                git_status = f"[dim]{repo.current_branch}[/dim]"
        else:
            git_status = "[dim]remote[/dim]"

        # Language tag
        lang_tag = f"[cyan]{repo.language}[/cyan]" if repo.language else ""

        # Cloud tag
        cloud_tag = f"[magenta]{repo.cloud_env}[/magenta]" if repo.cloud_env else ""

        # SonarCloud status
        sonar_info = ""
        if repo.sonar_status:
            status = repo.sonar_status.status
            if status == "ERROR":
                sonar_info = "[red]✗ Sonar[/red]"
            elif status == "WARN":
                sonar_info = "[yellow]⚠ Sonar[/yellow]"
            elif status == "OK":
                sonar_info = "[green]✓ Sonar[/green]"
        elif repo.sonar_checked:
            sonar_info = "[dim]No Sonar[/dim]"

        # Activity indicator (basic heuristic)
        activity = ""
        total_items = issue_count + pr_count
        if total_items >= 5:
            activity = "[red]🔥 active[/red]"
        elif total_items >= 2:
            activity = "[yellow]🟡 moderate[/yellow]"
        elif total_items == 0:
            activity = "[green]🟢 stable[/green]"

        # Build card content
        lines = [
            f"[bold]{repo.name}[/bold]",
            "",
            f"{lang_tag} {cloud_tag}".strip(),
            f"[dim]{counts}[/dim]",
            f"{git_status}",
            "",
            f"{sonar_info} {activity}".strip(),
        ]

        return "\n".join(line for line in lines if line or line == "")


class RepoGridWidget(VerticalScroll):
    """Grid view showing repositories as cards."""

    DEFAULT_CSS = """
    RepoGridWidget {
        height: 1fr;
    }

    #repo-grid-container {
        layout: grid;
        grid-size: 3;
        grid-gutter: 1 2;
        padding: 1;
    }

    .repo-card {
        height: 11;
        border: solid $primary;
        padding: 1;
        text-align: center;
    }

    .repo-card:focus {
        border: solid $accent;
        background: $boost;
    }
    """

    class RepoSelected(Message):
        """Posted when a repo is selected."""

        def __init__(self, repo: RepoOverview) -> None:
            super().__init__()
            self.repo = repo

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.repos: list[RepoOverview] = []
        self._cards: list[RepoCard] = []

    def compose(self):
        """Compose the grid container."""
        yield Grid(id="repo-grid-container")

    def set_repos(self, repos: list[RepoOverview]) -> None:
        """Set the repositories to display."""
        self.repos = repos

        # Clear existing cards
        grid = self.query_one("#repo-grid-container", Grid)
        grid.remove_children()
        self._cards = []

        # Sort repos (same logic as list view)
        sorted_repos = sorted(repos, key=self._get_priority, reverse=True)

        # Create cards
        for repo in sorted_repos:
            card = RepoCard(repo)
            grid.mount(card)
            self._cards.append(card)

        # Focus first card if any
        if self._cards:
            self._cards[0].focus()

    def _get_priority(self, repo: RepoOverview) -> int:
        """Calculate sort priority for a repo (same as list view)."""
        priority = 0

        # SonarCloud failures get highest priority
        if repo.sonar_status and repo.sonar_status.status == "ERROR":
            priority += 1000

        # Uncommitted changes
        if repo.has_uncommitted_changes:
            priority += 500

        # Issue/PR count
        priority += repo.open_issues_count * 10
        if repo.pull_requests:
            priority += len(repo.pull_requests) * 10

        # Local repos higher priority
        if repo.local_path:
            priority += 100

        return priority

    def get_selected_repo(self) -> RepoOverview | None:
        """Get the currently selected repository."""
        focused = self.app.focused
        if isinstance(focused, RepoCard):
            return focused.repo
        return None

    def action_cursor_down(self) -> None:
        """Move cursor down in grid (3 cards = 1 row)."""
        focused = self.app.focused
        if not isinstance(focused, RepoCard):
            return

        try:
            current_idx = self._cards.index(focused)
            next_idx = min(current_idx + 3, len(self._cards) - 1)
            if next_idx != current_idx:
                self._cards[next_idx].focus()
        except (ValueError, IndexError):
            pass

    def action_cursor_up(self) -> None:
        """Move cursor up in grid (3 cards = 1 row)."""
        focused = self.app.focused
        if not isinstance(focused, RepoCard):
            return

        try:
            current_idx = self._cards.index(focused)
            prev_idx = max(current_idx - 3, 0)
            if prev_idx != current_idx:
                self._cards[prev_idx].focus()
        except (ValueError, IndexError):
            pass

    def action_cursor_left(self) -> None:
        """Move cursor left in grid."""
        focused = self.app.focused
        if not isinstance(focused, RepoCard):
            return

        try:
            current_idx = self._cards.index(focused)
            if current_idx > 0:
                self._cards[current_idx - 1].focus()
        except (ValueError, IndexError):
            pass

    def action_cursor_right(self) -> None:
        """Move cursor right in grid."""
        focused = self.app.focused
        if not isinstance(focused, RepoCard):
            return

        try:
            current_idx = self._cards.index(focused)
            if current_idx < len(self._cards) - 1:
                self._cards[current_idx + 1].focus()
        except (ValueError, IndexError):
            pass

    def get_selected_inline_issue(self):
        """Grid view doesn't support inline issues (no expansion)."""
        return None

    def get_selected_inline_pr(self):
        """Grid view doesn't support inline PRs (no expansion)."""
        return None
