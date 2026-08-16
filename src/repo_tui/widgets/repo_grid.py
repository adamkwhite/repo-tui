"""Grid view widget for repository overview."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.containers import Grid, VerticalScroll
from textual.message import Message
from textual.widgets import Static

if TYPE_CHECKING:
    from ..models import RepoOverview


# One function per line of the card. Module-level and pure, so each is testable
# against a RepoOverview without mounting a widget.


def card_counts(repo: RepoOverview) -> str:
    """Issue and PR counts, or the failure marker when they are unknown."""
    if repo.fetch_failed:
        # Not "No issues or PRs" — gh failed, so the counts are unknown.
        return "[magenta]◌ fetch failed[/magenta]"

    parts = []
    if repo.open_issues_count:
        label = "issue" if repo.open_issues_count == 1 else "issues"
        parts.append(f"[cyan]{repo.open_issues_count}[/cyan] {label}")
    pr_count = len(repo.pull_requests) if repo.pull_requests else 0
    if pr_count:
        parts.append(f"[green]{pr_count}[/green] {'PR' if pr_count == 1 else 'PRs'}")
    return ", ".join(parts) if parts else "[dim]No issues or PRs[/dim]"


def card_git_status(repo: RepoOverview) -> str:
    """Checkout state for the card's second line."""
    if not repo.local_path:
        return "[dim]remote[/dim]"
    if repo.has_uncommitted_changes is None:
        return "[magenta]◌ git status unknown[/magenta]"
    if repo.has_uncommitted_changes:
        return f"[yellow]✱ {repo.current_branch or 'local'}[/yellow]"
    if repo.current_branch:
        return f"[dim]⎇ {repo.current_branch}[/dim]"
    return "[dim]local[/dim]"


def card_tags(repo: RepoOverview) -> str:
    """Language and cloud tags, joined, or empty when the repo has neither."""
    tags = []
    if repo.language:
        tags.append(f"[cyan]{repo.language}[/cyan]")
    if repo.cloud_env:
        tags.append(f"[magenta]{repo.cloud_env}[/magenta]")
    return " · ".join(tags)


def card_sonar(repo: RepoOverview) -> str:
    """Quality gate marker; the card has no room for the failing metric names."""
    if repo.sonar_status:
        return {
            "ERROR": "[red]✗ Sonar[/red]",
            "WARN": "[yellow]⚠ Sonar[/yellow]",
            "OK": "[green]✓ Sonar[/green]",
        }.get(repo.sonar_status.status, "")
    if repo.sonar_unreachable:
        return "[magenta]◌ Sonar unreachable[/magenta]"
    return ""


def card_activity(repo: RepoOverview) -> str:
    """Traffic-light heuristic on open work. Empty when we failed to read the repo."""
    if repo.fetch_failed or repo.has_uncommitted_changes is None:
        return ""  # No green "all clear" for a repo we failed to read.

    total = repo.open_issues_count + (len(repo.pull_requests) if repo.pull_requests else 0)
    if total >= 5:
        return "🔥"
    if total >= 2:
        return "🟡"
    if total == 0:
        return "🟢"
    return ""


class RepoCard(Static):
    """A single repository card in the grid."""

    def __init__(self, repo: RepoOverview) -> None:
        self.repo = repo
        content = self._build_content()
        super().__init__(content)
        self.add_class("repo-card")
        self.can_focus = True

    def _build_content(self) -> str:
        """Assemble the card from the line builders below."""
        repo = self.repo

        lines = ["", f"[bold white]{repo.display_name}[/bold white]", ""]

        tags_line = card_tags(repo)
        if tags_line:
            lines += [tags_line, ""]

        lines += [card_counts(repo), card_git_status(repo)]

        if repo.pushed_at_relative:
            lines.append(f"[dim]{repo.pushed_at_relative}[/dim]")

        bottom = [part for part in (card_sonar(repo), card_activity(repo)) if part]
        if bottom:
            lines += ["", " ".join(bottom)]

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

        # Textual's own logger, not a file: this ran on every render, ungated by
        # the debug flag, into a fixed path in the shared temp dir.
        self.log(f"grid set_repos: {len(sorted_repos)} repos")

        # Create cards
        for repo in sorted_repos:
            try:
                card = RepoCard(repo)
                grid.mount(card)
                self._cards.append(card)
            except Exception as e:
                # One malformed repo must not leave the grid empty.
                self.log.error(f"grid card failed for {repo.name}: {e}")

        self.log(f"grid mounted {len(self._cards)} cards")

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
