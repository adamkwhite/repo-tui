"""Data models for repo overview."""

from dataclasses import dataclass
from typing import List, Dict, Optional


@dataclass
class Issue:
    """GitHub Issue data."""
    number: int
    title: str
    url: str
    labels: List[str]
    state: str
    body: str = ""
    assignee: Optional[str] = None


@dataclass
class SonarStatus:
    """SonarCloud quality gate status."""
    project_key: str
    status: str  # OK, ERROR, WARN, NONE
    url: str
    conditions: List[Dict[str, str]]


@dataclass
class RepoOverview:
    """Repository overview with issues and SonarCloud status."""
    name: str
    owner: str
    url: str
    open_issues_count: int
    issues: List[Issue]
    sonar_status: Optional[SonarStatus]
    local_path: Optional[str] = None  # Path if repo exists locally
