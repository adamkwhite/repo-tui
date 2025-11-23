"""Repository list widget."""

from typing import List, Optional

from textual.widgets import OptionList
from textual.widgets.option_list import Option
from textual.message import Message
from rich.text import Text

from ..models import RepoOverview


class RepoListWidget(OptionList):
    """Scrollable list of repositories with status indicators."""

    class RepoSelected(Message):
        """Event emitted when a repo is selected."""
        def __init__(self, repo: Optional[RepoOverview]):
            self.repo = repo
            super().__init__()

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.repos: List[RepoOverview] = []
        self.expanded: set = set()  # Set of expanded repo names

    def set_repos(self, repos: List[RepoOverview]) -> None:
        """Update the list with new repos."""
        self.repos = repos
        self._rebuild_options()
        # Select first repo by default
        if self.repos:
            self.highlighted = 0

    def _rebuild_options(self) -> None:
        """Rebuild the option list from current repos."""
        self.clear_options()

        # Sort by priority: failed QG first, then by issue count
        sorted_repos = sorted(
            self.repos,
            key=lambda r: self._get_priority(r),
            reverse=True
        )

        for repo in sorted_repos:
            option = self._build_repo_option(repo)
            self.add_option(option)

            # If expanded, add issues as indented items
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
        # Status icon
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

        # Expand indicator
        expand_icon = "▼" if repo.name in self.expanded else "▶"

        # Issue count badge
        if repo.open_issues_count > 0:
            badge = f" [dim]({repo.open_issues_count})[/dim]"
        else:
            badge = ""

        # Local indicator - escape brackets to avoid Rich parsing [remote] as a style
        local = "" if repo.local_path else " [dim]\\[remote][/dim]"

        text = Text.from_markup(f"{icon} {expand_icon} {repo.name}{badge}{local}")
        return Option(text, id=f"repo:{repo.name}")

    def _build_issue_option(self, repo: RepoOverview, issue) -> Option:
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
            # Restore selection to the same repo
            self._select_by_id(f"repo:{repo_name}")

    def _select_by_id(self, option_id: str) -> None:
        """Select an option by its ID."""
        for i in range(self.option_count):
            option = self.get_option_at_index(i)
            if option and option.id == option_id:
                self.highlighted = i
                break

    def get_selected_repo(self) -> Optional[RepoOverview]:
        """Get the currently selected repository."""
        selected = self.highlighted
        if selected is None:
            return None

        option = self.get_option_at_index(selected)
        if not option or not option.id:
            return None

        # Parse the option ID to get repo name
        if option.id.startswith("repo:"):
            repo_name = option.id.split(":", 1)[1]
        elif option.id.startswith("issue:"):
            # issue:repo_name:issue_number
            repo_name = option.id.split(":")[1]
        else:
            return None

        # Find the repo
        for repo in self.repos:
            if repo.name == repo_name:
                return repo
        return None

    def get_selected_inline_issue(self) -> Optional[tuple]:
        """Get the issue if an inline issue is selected.

        Returns (repo, issue) tuple or None if a repo row is selected.
        """
        selected = self.highlighted
        if selected is None:
            return None

        option = self.get_option_at_index(selected)
        if not option or not option.id:
            return None

        # Check if it's an inline issue
        if option.id.startswith("issue:"):
            # issue:repo_name:issue_number
            parts = option.id.split(":")
            if len(parts) >= 3:
                repo_name = parts[1]
                try:
                    issue_number = int(parts[2])
                except ValueError:
                    return None

                # Find the repo and issue
                for repo in self.repos:
                    if repo.name == repo_name:
                        for issue in repo.issues:
                            if issue.number == issue_number:
                                return (repo, issue)
        return None

    def on_option_list_option_highlighted(self, event) -> None:
        """Emit event when selection changes."""
        repo = self.get_selected_repo()
        self.post_message(self.RepoSelected(repo))
