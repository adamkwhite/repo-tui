"""Issue list widget."""

from typing import List, Optional

from textual.widgets import OptionList
from textual.widgets.option_list import Option
from rich.text import Text

from ..models import Issue


class IssueListWidget(OptionList):
    """Scrollable list of issues for the selected repository."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.issues: List[Issue] = []
        self._current_index: int = 0  # Track our own cursor

    def set_issues(self, issues: List[Issue]) -> None:
        """Update the list with issues from selected repo."""
        self.issues = issues
        self._rebuild_options()
        # Always highlight first item if there are issues
        self._current_index = 0
        if self.issues:
            self.highlighted = 0

    def action_cursor_down(self) -> None:
        """Move cursor down and track index."""
        super().action_cursor_down()
        self._sync_current_index()

    def action_cursor_up(self) -> None:
        """Move cursor up and track index."""
        super().action_cursor_up()
        self._sync_current_index()

    def on_option_list_option_highlighted(self, event) -> None:
        """Sync our index when highlight changes."""
        self._sync_current_index()

    def _sync_current_index(self) -> None:
        """Sync _current_index with highlighted."""
        if self.highlighted is not None:
            self._current_index = self.highlighted

    def _rebuild_options(self, preserve_highlight: bool = False) -> None:
        """Rebuild the option list from current issues."""
        old_highlighted = self.highlighted
        self.clear_options()

        if not self.issues:
            self.add_option(Option(Text.from_markup("[dim]No open issues[/dim]"), id="empty"))
            return

        for issue in self.issues:
            option = self._build_issue_option(issue)
            self.add_option(option)

        # Restore highlight if requested and valid
        if preserve_highlight and old_highlighted is not None:
            if old_highlighted < len(self.issues):
                self.highlighted = old_highlighted

    def _build_issue_option(self, issue: Issue) -> Option:
        """Build a rich option for an issue."""
        # Truncate title
        max_len = 50
        title = issue.title[:max_len-1] + "…" if len(issue.title) > max_len else issue.title

        # Format labels
        labels = ""
        if issue.labels:
            label_text = ", ".join(issue.labels[:3])  # Max 3 labels
            if len(issue.labels) > 3:
                label_text += "…"
            labels = f" [dim]({label_text})[/dim]"

        text = Text.from_markup(f"[cyan]#{issue.number}[/cyan] {title}{labels}")
        return Option(text, id=f"issue:{issue.number}")

    def get_selected_issue(self) -> Optional[Issue]:
        """Get the currently selected issue."""
        if not self.issues:
            return None

        # Use our tracked index
        if 0 <= self._current_index < len(self.issues):
            return self.issues[self._current_index]

        return None
