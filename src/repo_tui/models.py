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
class SonarStatus:
    """SonarCloud quality gate status."""

    project_key: str
    status: str  # OK, ERROR, WARN, NONE
    url: str
    conditions: list[dict[str, str]]


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
