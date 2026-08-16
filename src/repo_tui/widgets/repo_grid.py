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
        self.repo = repo
        content = self._build_content()
        super().__init__(content)
        self.add_class("repo-card")
        self.can_focus = True

    def _build_content(self) -> str:
        """Render the card content."""
        repo = self.repo

        # Build counts
        issue_count = repo.open_issues_count
        pr_count = len(repo.pull_requests) if repo.pull_requests else 0

        counts_parts = []
        if issue_count > 0:
            issue_label = "issue" if issue_count == 1 else "issues"
            counts_parts.append(f"[cyan]{issue_count}[/cyan] {issue_label}")
        if pr_count > 0:
            pr_label = "PR" if pr_count == 1 else "PRs"
            counts_parts.append(f"[green]{pr_count}[/green] {pr_label}")
        counts = ", ".join(counts_parts) if counts_parts else "[dim]No issues or PRs[/dim]"
        if repo.fetch_failed:
            # Not "No issues or PRs" — gh failed, so the counts are unknown.
            counts = "[magenta]◌ fetch failed[/magenta]"

        # Git status
        if repo.local_path:
            if repo.has_uncommitted_changes is None:
                git_status = "[magenta]◌ git status unknown[/magenta]"
            elif repo.has_uncommitted_changes:
                git_status = f"[yellow]✱ {repo.current_branch or 'local'}[/yellow]"
            elif repo.current_branch:
                git_status = f"[dim]⎇ {repo.current_branch}[/dim]"
            else:
                git_status = "[dim]local[/dim]"
        else:
            git_status = "[dim]remote[/dim]"

        # Tags line (language and/or cloud)
        tags = []
        if repo.language:
            tags.append(f"[cyan]{repo.language}[/cyan]")
        if repo.cloud_env:
            tags.append(f"[magenta]{repo.cloud_env}[/magenta]")
        tags_line = " · ".join(tags) if tags else ""

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
        elif repo.sonar_unreachable:
            sonar_info = "[magenta]◌ Sonar unreachable[/magenta]"

        # Activity indicator (basic heuristic)
        activity = ""
        total_items = issue_count + pr_count
        if repo.fetch_failed or repo.has_uncommitted_changes is None:
            activity = ""  # No green "all clear" for a repo we failed to read.
        elif total_items >= 5:
            activity = "🔥"
        elif total_items >= 2:
            activity = "🟡"
        elif total_items == 0:
            activity = "🟢"

        # Build card content - always show name prominently
        lines = [
            "",  # Top padding
            f"[bold white]{repo.display_name}[/bold white]",
            "",
        ]

        # Tags (if any)
        if tags_line:
            lines.append(tags_line)
            lines.append("")

        # Always show counts and git status
        lines.append(counts)
        lines.append(git_status)

        # Last push date
        if repo.pushed_at_relative:
            lines.append(f"[dim]{repo.pushed_at_relative}[/dim]")

        # Bottom line: sonar and/or activity
        bottom_parts = []
        if sonar_info:
            bottom_parts.append(sonar_info)
        if activity:
            bottom_parts.append(activity)

        if bottom_parts:
            lines.append("")
            lines.append(" ".join(bottom_parts))

        return "\n".join(lines)


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
        sorted_repos = sorted(repos, key=lambda r: r.pushed_at or "", reverse=True)

        # Debug: log to file
        with open("/tmp/grid_debug.log", "a") as f:
            f.write("\n=== set_repos called ===\n")
            f.write(f"Total repos: {len(sorted_repos)}\n")
            for i, repo in enumerate(sorted_repos[:10]):
                f.write(
                    f"  {i}: {repo.name} - issues:{repo.open_issues_count} branch:{repo.current_branch}\n"
                )

        # Create cards
        for repo in sorted_repos:
            try:
                card = RepoCard(repo)
                grid.mount(card)
                self._cards.append(card)
            except Exception as e:
                with open("/tmp/grid_debug.log", "a") as f:
                    f.write(f"ERROR creating card for {repo.name}: {e}\n")

        with open("/tmp/grid_debug.log", "a") as f:
            f.write(f"Created {len(self._cards)} cards successfully\n")

        # Focus first card if any
        if self._cards:
            self._cards[0].focus()

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
