"""Repository list widget."""

from __future__ import annotations

from datetime import UTC
from typing import TYPE_CHECKING

from rich.markup import escape
from rich.text import Text
from textual.message import Message
from textual.widgets import OptionList
from textual.widgets.option_list import Option

from ..models import RepoOverview, redact_text

if TYPE_CHECKING:
    from ..models import Issue, PullRequest


SPECIAL_ACTION_DEPENDABOT = "dependabot-merge"

# The row is assembled from independent badges. They are module-level and pure
# so each can be tested against a RepoOverview without mounting a widget, and
# so the row builder stays a single line of composition per badge.


def status_icon(repo: RepoOverview) -> str:
    """Colored dot summarising the repo, highest-priority signal wins.

    Order matters: "unknown" must outrank the green clean state, or a repo we
    failed to read renders as healthier than one with a single open issue.
    """
    if repo.fetch_failed or repo.has_uncommitted_changes is None:
        return "[magenta]◌[/magenta]"  # nothing was read; not a verdict
    if repo.sonar_status and repo.sonar_status.status == "ERROR":
        return "[red]●[/red]"
    if repo.critical_issue_count >= 5:
        return "[red]●[/red]"
    if repo.sonar_status and repo.sonar_status.status == "WARN":
        return "[yellow]●[/yellow]"
    if repo.has_uncommitted_changes:
        return "[yellow]●[/yellow]"
    if repo.critical_issue_count > 0:
        return "[yellow]●[/yellow]"
    if repo.pull_requests:
        return "[blue]●[/blue]"  # work in progress
    return "[green]●[/green]"


def counts_badge(repo: RepoOverview) -> str:
    """ "2 PRs, 3 issues", or the failure marker when the counts are unknown."""
    if repo.fetch_failed:
        return " [magenta]fetch failed[/magenta]"

    parts = []
    pr_count = len(repo.pull_requests) if repo.pull_requests else 0
    if pr_count:
        parts.append(f"{pr_count} {'PR' if pr_count == 1 else 'PRs'}")
    if repo.open_issues_count:
        parts.append(
            f"{repo.open_issues_count} {'issue' if repo.open_issues_count == 1 else 'issues'}"
        )
    return f" [dim]{', '.join(parts)}[/dim]" if parts else ""


def local_badge(repo: RepoOverview) -> str:
    """Checkout state: branch, uncommitted work, unknown, or remote-only."""
    if not repo.local_path:
        return " [dim]\\[remote][/dim]"
    if repo.has_uncommitted_changes is None:
        return " [magenta]git status unknown[/magenta]"
    if repo.has_uncommitted_changes:
        branch_info = f" on {repo.current_branch}" if repo.current_branch else ""
        return f" [yellow]✱ uncommitted{branch_info}[/yellow]"
    if repo.current_branch:
        return f" [dim]\\[{repo.current_branch}][/dim]"
    return ""


def sonar_badge(repo: RepoOverview) -> str:
    """Quality gate result, naming the failing metrics when the gate is red."""
    if repo.sonar_status:
        status = repo.sonar_status.status
        if status == "ERROR":
            failed = [
                c["metricKey"] for c in repo.sonar_status.conditions if c.get("status") == "ERROR"
            ]
            return f" [red]✗ {', '.join(failed[:3]) if failed else 'Quality Gate'}[/red]"
        if status == "WARN":
            return " [yellow]⚠ Quality Gate[/yellow]"
        if status == "OK":
            return " [green]✓ Sonar[/green]"
        return ""
    if repo.sonar_unreachable:
        # We asked and could not get an answer — not the same as "no project".
        return " [magenta]◌ Sonar unreachable[/magenta]"
    if repo.sonar_checked:
        return " [dim]No Sonar[/dim]"
    return ""


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
            # Land on the first real repo, not the special action row at index 0.
            self.highlighted = 1

    def _rebuild_options(self) -> None:
        """Rebuild the option list from current repos."""
        self.clear_options()

        self.add_option(self._build_dependabot_action_option())

        sorted_repos = sorted(
            self.repos,
            key=lambda r: r.pushed_at or "",
            reverse=True,
        )

        for repo in sorted_repos:
            self.add_option(self._build_repo_option(repo))
            if repo.name in self.expanded:
                for option in self._expanded_child_options(repo):
                    self.add_option(option)

    def _expanded_child_options(self, repo: RepoOverview) -> list[Option]:
        """Rows shown beneath an expanded repo: description, then PRs, then issues."""
        options = [self._build_description_option(repo)]
        options += [self._build_pr_option(repo, pr) for pr in repo.pull_requests or []]
        options += [self._build_issue_option(repo, issue) for issue in repo.issues]
        return options

    def _build_dependabot_action_option(self) -> Option:
        """Build the special pseudo-row that triggers the Dependabot bulk merger."""
        text = Text.from_markup(
            "[bold cyan]⚡ Merge Dependabot PRs[/bold cyan]"
            " [dim]— bulk-merge across all repos (press Space/Enter)[/dim]"
        )
        return Option(text, id=f"action:{SPECIAL_ACTION_DEPENDABOT}")

    def get_selected_special_action(self) -> str | None:
        """Return the special-action id if the action row is highlighted."""
        selected = self.highlighted
        if selected is None:
            return None
        option = self.get_option_at_index(selected)
        option_id: str | None = option.id if option else None
        if option_id and option_id.startswith("action:"):
            return option_id.split(":", 1)[1]
        return None

    def _build_repo_option(self, repo: RepoOverview) -> Option:
        """Build a rich option for a repository."""
        expand_icon = "▼" if repo.name in self.expanded else "▶"
        lang_tag = f" [cyan]\\[{repo.language}][/cyan]" if repo.language else ""
        cloud_tag = f" [magenta]\\[{repo.cloud_env}][/magenta]" if repo.cloud_env else ""
        pushed_tag = f" [dim]{repo.pushed_at_relative}[/dim]" if repo.pushed_at_relative else ""

        text = Text.from_markup(
            f"{status_icon(repo)} {expand_icon} {repo.display_name}"
            f"{lang_tag}{cloud_tag}{counts_badge(repo)}{local_badge(repo)}"
            f"{pushed_tag}{sonar_badge(repo)}"
        )
        return Option(text, id=f"repo:{repo.name}")

    def _build_issue_option(self, repo: RepoOverview, issue: Issue) -> Option:
        """Build a rich option for an issue (indented under repo)."""
        title = (
            redact_text(issue.title)
            if (RepoOverview.privacy_mode and repo.is_private)
            else issue.title
        )
        text = Text.from_markup(f"    [dim]#{issue.number}[/dim] {escape(title)}")
        return Option(text, id=f"issue:{repo.name}:{issue.number}")

    def _build_pr_option(self, repo: RepoOverview, pr: PullRequest) -> Option:
        """Build a rich option for a PR (indented under repo)."""
        draft = "[dim]draft[/dim] " if pr.draft else ""

        # Extract date from created_at and color-code based on age
        date_str = ""
        if pr.created_at:
            from datetime import datetime

            date_only = pr.created_at.split("T")[0]

            # Calculate age in days
            try:
                created_date = datetime.fromisoformat(pr.created_at.replace("Z", "+00:00"))
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
        _private = RepoOverview.privacy_mode and repo.is_private
        title = redact_text(pr.title) if _private else pr.title
        text = Text.from_markup(
            f"    [green]PR #{pr.number}[/green] {draft}{date_str}{author}{escape(title)}"
        )
        return Option(text, id=f"pr:{repo.name}:{pr.number}")

    def _build_description_option(self, repo: RepoOverview) -> Option:
        """Build a rich option for the repo description."""
        desc = repo.description if repo.description else "No description"
        if RepoOverview.privacy_mode and repo.is_private:
            desc = redact_text(desc)
        text = Text.from_markup(f"    [white italic]{escape(desc)}[/white italic]")
        return Option(text, id=f"desc:{repo.name}", disabled=True)

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

    def _highlighted_option_id(self) -> str | None:
        """Option id of the highlighted row, or None if nothing is highlighted."""
        selected = self.highlighted
        if selected is None:
            return None
        option = self.get_option_at_index(selected)
        return option.id if option else None

    def _repo_by_name(self, name: str) -> RepoOverview | None:
        return next((repo for repo in self.repos if repo.name == name), None)

    def _selected_child_row(self, prefix: str) -> tuple[RepoOverview, int] | None:
        """Resolve a `<prefix>:<repo>:<number>` row to its repo and number.

        Both inline-child getters below parse the same id shape, so the parsing
        (and its failure modes: no selection, wrong row type, malformed id,
        unknown repo) lives here once.
        """
        option_id = self._highlighted_option_id()
        if not option_id or not option_id.startswith(f"{prefix}:"):
            return None

        parts = option_id.split(":")
        if len(parts) < 3:
            return None
        try:
            number = int(parts[2])
        except ValueError:
            return None

        repo = self._repo_by_name(parts[1])
        return (repo, number) if repo else None

    def get_selected_repo(self) -> RepoOverview | None:
        """Get the currently selected repository."""
        option_id = self._highlighted_option_id()
        if not option_id:
            return None

        # Child rows carry their parent repo name in the same position, so an
        # issue or PR row still resolves to the repo it belongs to.
        if option_id.startswith(("repo:", "issue:", "pr:")):
            return self._repo_by_name(option_id.split(":")[1])
        return None

    def get_selected_inline_issue(self) -> tuple[RepoOverview, Issue] | None:
        """Get the issue if an inline issue is selected.

        Returns (repo, issue) tuple or None if a repo row is selected.
        """
        match = self._selected_child_row("issue")
        if not match:
            return None
        repo, number = match
        issue = next((i for i in repo.issues if i.number == number), None)
        return (repo, issue) if issue else None

    def get_selected_inline_pr(self) -> tuple[RepoOverview, PullRequest] | None:
        """Get the PR if an inline PR is selected.

        Returns (repo, pr) tuple or None if a repo/issue row is selected.
        """
        match = self._selected_child_row("pr")
        if not match:
            return None
        repo, number = match
        pr = next((p for p in (repo.pull_requests or []) if p.number == number), None)
        return (repo, pr) if pr else None

    def on_option_list_option_highlighted(
        self,
        event: OptionList.OptionHighlighted,  # noqa: ARG002
    ) -> None:
        """Emit event when selection changes."""
        repo = self.get_selected_repo()
        self.post_message(self.RepoSelected(repo))
