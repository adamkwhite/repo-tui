"""Repository list widget."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.text import Text
from textual.message import Message
from textual.widgets import OptionList
from textual.widgets.option_list import Option, OptionListOptionHighlighted

if TYPE_CHECKING:
    from ..models import Issue, RepoOverview


class RepoListWidget(OptionList):
    """Scrollable list of repositories with status indicators."""

    class RepoSelected(Message):
        """Event emitted when a repo is selected."""

        def __init__(self, repo: RepoOverview | None) -> None:
            self.repo = repo
            super().__init__()

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.repos: list[RepoOverview] = []
        self.expanded: set[str] = set()

    def set_repos(self, repos: list[RepoOverview]) -> None:
        """Update the list with new repos."""
        self.repos = repos
        self._rebuild_options()
        if self.repos:
            self.highlighted = 0

    def _rebuild_options(self) -> None:
        """Rebuild the option list from current repos."""
        self.clear_options()

        sorted_repos = sorted(
            self.repos,
            key=lambda r: self._get_priority(r),
            reverse=True,
        )

        for repo in sorted_repos:
            option = self._build_repo_option(repo)
            self.add_option(option)

            if repo.name in self.expanded:
                for issue in repo.issues:
                    issue_option = self._build_issue_option(repo, issue)
                    self.add_option(issue_option)

    def _get_priority(self, repo: RepoOverview) -> int:
        """Calculate sort priority for a repo."""
        priority = 0
        if repo.sonar_status:
            if repo.sonar_status.status == "ERROR":
                priority += 1000
            elif repo.sonar_status.status == "WARN":
                priority += 100
        priority += repo.open_issues_count
        return priority

    def _build_repo_option(self, repo: RepoOverview) -> Option:
        """Build a rich option for a repository."""
        if repo.sonar_status and repo.sonar_status.status == "ERROR":
            icon = "[red]●[/red]"
        elif repo.sonar_status and repo.sonar_status.status == "WARN":
            icon = "[yellow]●[/yellow]"
        elif repo.open_issues_count >= 10:
            icon = "[red]●[/red]"
        elif repo.open_issues_count >= 5:
            icon = "[yellow]●[/yellow]"
        elif repo.open_issues_count > 0:
            icon = "[blue]●[/blue]"
        else:
            icon = "[green]●[/green]"

        expand_icon = "▼" if repo.name in self.expanded else "▶"
        badge = f" [dim]({repo.open_issues_count})[/dim]" if repo.open_issues_count > 0 else ""
        local = "" if repo.local_path else " [dim]\\[remote][/dim]"

        text = Text.from_markup(f"{icon} {expand_icon} {repo.name}{badge}{local}")
        return Option(text, id=f"repo:{repo.name}")

    def _build_issue_option(self, repo: RepoOverview, issue: Issue) -> Option:
        """Build a rich option for an issue (indented under repo)."""
        title = issue.title[:40] + "…" if len(issue.title) > 40 else issue.title
        text = Text.from_markup(f"    [dim]#{issue.number}[/dim] {title}")
        return Option(text, id=f"issue:{repo.name}:{issue.number}")

    def toggle_expand(self) -> None:
        """Toggle expand/collapse for currently selected repo."""
        selected = self.highlighted
        if selected is None:
            return

        option = self.get_option_at_index(selected)
        if option and option.id and option.id.startswith("repo:"):
            repo_name = option.id.split(":", 1)[1]
            if repo_name in self.expanded:
                self.expanded.discard(repo_name)
            else:
                self.expanded.add(repo_name)
            self._rebuild_options()
            self._select_by_id(f"repo:{repo_name}")

    def _select_by_id(self, option_id: str) -> None:
        """Select an option by its ID."""
        for i in range(self.option_count):
            option = self.get_option_at_index(i)
            if option and option.id == option_id:
                self.highlighted = i
                break

    def get_selected_repo(self) -> RepoOverview | None:
        """Get the currently selected repository."""
        selected = self.highlighted
        if selected is None:
            return None

        option = self.get_option_at_index(selected)
        if not option or not option.id:
            return None

        if option.id.startswith("repo:"):
            repo_name = option.id.split(":", 1)[1]
        elif option.id.startswith("issue:"):
            repo_name = option.id.split(":")[1]
        else:
            return None

        for repo in self.repos:
            if repo.name == repo_name:
                return repo
        return None

    def get_selected_inline_issue(self) -> tuple[RepoOverview, Issue] | None:
        """Get the issue if an inline issue is selected.

        Returns (repo, issue) tuple or None if a repo row is selected.
        """
        selected = self.highlighted
        if selected is None:
            return None

        option = self.get_option_at_index(selected)
        if not option or not option.id:
            return None

        if option.id.startswith("issue:"):
            parts = option.id.split(":")
            if len(parts) >= 3:
                repo_name = parts[1]
                try:
                    issue_number = int(parts[2])
                except ValueError:
                    return None

                for repo in self.repos:
                    if repo.name == repo_name:
                        for issue in repo.issues:
                            if issue.number == issue_number:
                                return (repo, issue)
        return None

    def on_option_list_option_highlighted(
        self,
        event: OptionListOptionHighlighted,  # noqa: ARG002
    ) -> None:
        """Emit event when selection changes."""
        repo = self.get_selected_repo()
        self.post_message(self.RepoSelected(repo))
