"""Data models for repo overview."""

from __future__ import annotations

from dataclasses import dataclass


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


@dataclass
class SonarStatus:
    """SonarCloud quality gate status."""

    project_key: str
    status: str  # OK, ERROR, WARN, NONE
    url: str
    conditions: list[dict[str, str]]


# Cloud-related topic keywords to detect cloud environment
CLOUD_TOPICS = {"aws", "azure", "gcp", "cloudflare", "vercel", "heroku", "digitalocean"}


@dataclass
class RepoOverview:
    """Repository overview with issues and SonarCloud status."""

    name: str
    owner: str
    url: str
    open_issues_count: int
    issues: list[Issue]
    sonar_status: SonarStatus | None
    local_path: str | None = None
    sonar_checked: bool = False  # True if we attempted to check SonarCloud
    language: str | None = None  # Primary programming language
    topics: list[str] | None = None  # Repository topics/tags
    pull_requests: list[PullRequest] | None = None  # Open pull requests
    details_loaded: bool = False  # True if issues/PRs have been fetched
    has_uncommitted_changes: bool = False  # True if local repo has uncommitted changes
    current_branch: str | None = None  # Current git branch if local repo exists
    description: str | None = None  # Repository description

    @property
    def cloud_env(self) -> str | None:
        """Extract cloud environment from topics."""
        if not self.topics:
            return None
        for topic in self.topics:
            if topic.lower() in CLOUD_TOPICS:
                return topic.lower()
        return None
