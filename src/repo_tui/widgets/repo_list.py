"""Repository list widget."""

from __future__ import annotations

from datetime import UTC
from typing import TYPE_CHECKING

from rich.text import Text
from textual.message import Message
from textual.widgets import OptionList
from textual.widgets.option_list import Option

if TYPE_CHECKING:
    from ..models import Issue, PullRequest, RepoOverview


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
                # Show PRs and issues
                if repo.pull_requests:
                    for pr in repo.pull_requests:
                        pr_option = self._build_pr_option(repo, pr)
                        self.add_option(pr_option)
                if repo.issues:
                    for issue in repo.issues:
                        issue_option = self._build_issue_option(repo, issue)
                        self.add_option(issue_option)

                # If no PRs or issues, show empty state with description
                if not repo.pull_requests and not repo.issues:
                    empty_option = self._build_empty_option(repo)
                    self.add_option(empty_option)

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
        issue_count = repo.open_issues_count
        pr_count = len(repo.pull_requests) if repo.pull_requests else 0

        # Build counts display
        counts_parts = []
        if pr_count > 0:
            counts_parts.append(f"{pr_count} PRs")
        if issue_count > 0:
            counts_parts.append(f"{issue_count} issues")
        counts_badge = f" [dim]{', '.join(counts_parts)}[/dim]" if counts_parts else ""

        # Local/remote indicator with branch info
        local = ""
        if repo.local_path:
            if repo.has_uncommitted_changes:
                branch_info = f" on {repo.current_branch}" if repo.current_branch else ""
                local = f" [yellow]✱ uncommitted{branch_info}[/yellow]"
            elif repo.current_branch:
                local = f" [dim]\\[{repo.current_branch}][/dim]"
        else:
            local = " [dim]\\[remote][/dim]"

        # Language and cloud env tags
        lang_tag = f" [cyan]\\[{repo.language}][/cyan]" if repo.language else ""
        cloud_tag = f" [magenta]\\[{repo.cloud_env}][/magenta]" if repo.cloud_env else ""

        # SonarCloud status indicator
        sonar_info = ""
        if repo.sonar_status:
            status = repo.sonar_status.status
            if status == "ERROR":
                failed = [c["metricKey"] for c in repo.sonar_status.conditions if c.get("status") == "ERROR"]
                failed_text = ", ".join(failed[:3]) if failed else "Quality Gate"
                sonar_info = f" [red]✗ {failed_text}[/red]"
            elif status == "WARN":
                sonar_info = " [yellow]⚠ Quality Gate[/yellow]"
            elif status == "OK":
                sonar_info = " [green]✓ Sonar[/green]"
        elif repo.sonar_checked:
            # We checked but no SonarCloud project was found
            sonar_info = " [dim]No Sonar[/dim]"

        text = Text.from_markup(f"{icon} {expand_icon} {repo.name}{lang_tag}{cloud_tag}{counts_badge}{local}{sonar_info}")
        return Option(text, id=f"repo:{repo.name}")

    def _build_issue_option(self, repo: RepoOverview, issue: Issue) -> Option:
        """Build a rich option for an issue (indented under repo)."""
        text = Text.from_markup(f"    [dim]#{issue.number}[/dim] {issue.title}")
        return Option(text, id=f"issue:{repo.name}:{issue.number}")

    def _build_pr_option(self, repo: RepoOverview, pr: PullRequest) -> Option:
        """Build a rich option for a PR (indented under repo)."""
        draft = "[dim]draft[/dim] " if pr.draft else ""

        # Extract date from created_at and color-code based on age
        date_str = ""
        if pr.created_at:
            from datetime import datetime
            date_only = pr.created_at.split('T')[0]

            # Calculate age in days
            try:
                created_date = datetime.fromisoformat(pr.created_at.replace('Z', '+00:00'))
                now = datetime.now(UTC)
                age_days = (now - created_date).days

                # Color-code based on age
                if age_days < 7:
                    date_color = "green"
                elif age_days < 30:
                    date_color = "dim"
                elif age_days < 90:
                    date_color = "yellow"
                else:
                    date_color = "red"

                date_str = f"[{date_color}]on {date_only}[/{date_color}] "
            except (ValueError, AttributeError):
                # Fallback if date parsing fails
                date_str = f"[dim]on {date_only}[/dim] "

        # Prefer full name over username
        display_name = pr.author_name if pr.author_name else pr.author
        author = f"[dim]by {display_name}[/dim] " if display_name else ""
        text = Text.from_markup(f"    [green]PR #{pr.number}[/green] {draft}{date_str}{author}{pr.title}")
        return Option(text, id=f"pr:{repo.name}:{pr.number}")

    def _build_empty_option(self, repo: RepoOverview) -> Option:
        """Build a rich option for empty state (no issues or PRs)."""
        desc = repo.description if repo.description else "No description"
        text = Text.from_markup(f"    [dim]No issues or PRs[/dim]\n    [white italic]{desc}[/white italic]")
        return Option(text, id=f"empty:{repo.name}", disabled=True)

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
        elif option.id.startswith("issue:") or option.id.startswith("pr:"):
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

    def get_selected_inline_pr(self) -> tuple[RepoOverview, PullRequest] | None:
        """Get the PR if an inline PR is selected.

        Returns (repo, pr) tuple or None if a repo/issue row is selected.
        """
        selected = self.highlighted
        if selected is None:
            return None

        option = self.get_option_at_index(selected)
        if not option or not option.id:
            return None

        if option.id.startswith("pr:"):
            parts = option.id.split(":")
            if len(parts) >= 3:
                repo_name = parts[1]
                try:
                    pr_number = int(parts[2])
                except ValueError:
                    return None

                for repo in self.repos:
                    if repo.name == repo_name and repo.pull_requests:
                        for pr in repo.pull_requests:
                            if pr.number == pr_number:
                                return (repo, pr)
        return None

    def on_option_list_option_highlighted(
        self,
        event: OptionList.OptionHighlighted,  # noqa: ARG002
    ) -> None:
        """Emit event when selection changes."""
        repo = self.get_selected_repo()
        self.post_message(self.RepoSelected(repo))
