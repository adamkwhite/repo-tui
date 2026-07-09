"""Data models for repo overview."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass
class Issue:
    """GitHub Issue data."""

    number: int
    title: str
    url: str
    labels: list[str]
    state: str
    body: str = ""
    assignee: str | None = None


@dataclass
class PullRequest:
    """GitHub Pull Request data."""

    number: int
    title: str
    url: str
    author: str
    state: str
    draft: bool = False
    labels: list[str] | None = None
    body: str = ""
    reviewers: list[str] | None = None  # Requested reviewers
    review_decision: str | None = None  # APPROVED, CHANGES_REQUESTED, REVIEW_REQUIRED
    head_ref: str | None = None  # Source branch
    base_ref: str | None = None  # Target branch
    created_at: str | None = None
    updated_at: str | None = None
    mergeable: str | None = None  # MERGEABLE, CONFLICTING, UNKNOWN
    checks_status: str | None = None  # SUCCESS, FAILURE, PENDING
    author_name: str | None = None  # Full name of author (if available)


@dataclass
class SonarStatus:
    """SonarCloud quality gate status."""

    project_key: str
    status: str  # OK, ERROR, WARN, NONE
    url: str
    conditions: list[dict[str, str]]


# Cloud-related topic keywords to detect cloud environment
CLOUD_TOPICS = {"aws", "azure", "gcp", "cloudflare", "vercel", "heroku", "digitalocean"}


def mask_name(name: str) -> str:
    """Mask the middle of a name with asterisks, keeping first 2 and last 2 chars."""
    if len(name) <= 4:
        return "*" * len(name)
    return name[:2] + "*" * (len(name) - 4) + name[-2:]


def redact_text(text: str) -> str:
    """Replace each word with asterisks of matching length, preserving whitespace and punctuation."""
    import re

    return re.sub(r"\w+", lambda m: "*" * len(m.group()), text)


@dataclass
class RepoOverview:
    """Repository overview with issues and SonarCloud status."""

    privacy_mode = False

    name: str
    owner: str
    url: str
    open_issues_count: int
    issues: list[Issue]
    sonar_status: SonarStatus | None
    is_private: bool = False
    local_path: str | None = None
    sonar_checked: bool = False
    language: str | None = None
    topics: list[str] | None = None
    pull_requests: list[PullRequest] | None = None
    details_loaded: bool = False
    has_uncommitted_changes: bool = False
    current_branch: str | None = None
    description: str | None = None
    friendly_name: str | None = None
    pushed_at: str | None = None

    @property
    def pushed_at_relative(self) -> str | None:
        """Get a human-readable relative time for last push (e.g. '2d ago')."""
        if not self.pushed_at:
            return None
        try:
            pushed = datetime.fromisoformat(self.pushed_at.replace("Z", "+00:00"))
            delta = datetime.now(UTC) - pushed
            days = delta.days
            if days == 0:
                hours = delta.seconds // 3600
                if hours == 0:
                    return "just now"
                return f"{hours}h ago"
            if days < 7:
                return f"{days}d ago"
            if days < 30:
                weeks = days // 7
                return f"{weeks}w ago"
            if days < 365:
                months = days // 30
                return f"{months}mo ago"
            years = days // 365
            return f"{years}y ago"
        except (ValueError, AttributeError):
            return None

    @property
    def safe_name(self) -> str:
        """Repo name masked if private and privacy mode is on."""
        if RepoOverview.privacy_mode and self.is_private:
            return mask_name(self.name)
        return self.name

    @property
    def display_name(self) -> str:
        """Get the display name (friendly name if set, otherwise repo name)."""
        name = self.safe_name
        if self.friendly_name:
            friendly = (
                mask_name(self.friendly_name)
                if (RepoOverview.privacy_mode and self.is_private)
                else self.friendly_name
            )
            return f"{friendly} [dim]({name})[/dim]"
        return name

    @property
    def critical_issue_count(self) -> int:
        """Count issues with critical labels (bug, security, priority-high, etc.)."""
        critical_labels = {
            "bug",
            "security",
            "breaking-change",
            "ci-failure",
            "priority-high",
            "status-blocked",
        }
        count = 0
        for issue in self.issues:
            # Check if issue has any critical label
            if any(label.lower() in critical_labels for label in issue.labels):
                count += 1
        return count

    @property
    def cloud_env(self) -> str | None:
        """Extract cloud environment from topics."""
        if not self.topics:
            return None
        for topic in self.topics:
            if topic.lower() in CLOUD_TOPICS:
                return topic.lower()
        return None
