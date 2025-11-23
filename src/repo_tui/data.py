"""Data fetching clients for GitHub and SonarCloud."""

import asyncio
import json
import urllib.request
import urllib.parse
from pathlib import Path
from typing import List, Dict, Optional

from .models import Issue, SonarStatus, RepoOverview
from .config import Config


class GitHubClient:
    """GitHub API client using gh CLI."""

    def __init__(self, config: Config):
        self.config = config

    async def get_user_repos(self) -> List[Dict]:
        """Get all repositories for the authenticated user."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "gh", "repo", "list",
                "--json", "name,owner,url,hasIssuesEnabled",
                "--limit", "1000",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode != 0:
                return []

            repos = json.loads(stdout.decode())
            for repo in repos:
                repo["openIssuesCount"] = 0
            return repos
        except Exception:
            return []

    async def get_repo_issues(self, owner: str, repo: str) -> List[Issue]:
        """Get open issues for a repository."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "gh", "issue", "list",
                "--repo", f"{owner}/{repo}",
                "--json", "number,title,url,labels,state,body,assignees",
                "--limit", "100",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode != 0:
                return []

            issues_data = json.loads(stdout.decode())
            return [
                Issue(
                    number=issue["number"],
                    title=issue["title"],
                    url=issue["url"],
                    labels=[label["name"] for label in issue.get("labels", [])],
                    state=issue["state"],
                    body=issue.get("body", "") or "",
                    assignee=issue.get("assignees", [{}])[0].get("login") if issue.get("assignees") else None
                )
                for issue in issues_data
                if issue["state"] == "OPEN"
            ]
        except Exception:
            return []

    def get_local_repo_path(self, repo_name: str) -> Optional[Path]:
        """Check if repo exists locally and return path."""
        local_path = self.config.get_local_code_path() / repo_name
        if local_path.exists() and local_path.is_dir():
            return local_path
        return None


class SonarCloudClient:
    """SonarCloud API client for public projects."""

    BASE_URL = "https://sonarcloud.io/api"

    def __init__(self, config: Config):
        self.config = config

    async def get_project_status(self, project_key: str) -> Optional[SonarStatus]:
        """Get quality gate status for a project."""
        try:
            url = f"{self.BASE_URL}/qualitygates/project_status?projectKey={urllib.parse.quote(project_key)}"

            # Run blocking I/O in thread pool
            loop = asyncio.get_event_loop()
            data = await loop.run_in_executor(None, self._fetch_url, url)

            if data is None:
                return None

            project_status = data.get("projectStatus", {})
            return SonarStatus(
                project_key=project_key,
                status=project_status.get("status", "NONE"),
                url=f"https://sonarcloud.io/dashboard?id={urllib.parse.quote(project_key)}",
                conditions=project_status.get("conditions", [])
            )
        except Exception:
            return None

    def _fetch_url(self, url: str) -> Optional[Dict]:
        """Fetch URL and return JSON data."""
        try:
            with urllib.request.urlopen(url, timeout=10) as response:
                return json.loads(response.read().decode())
        except Exception:
            return None

    def guess_project_key(self, owner: str, repo: str) -> List[str]:
        """Generate possible SonarCloud project keys."""
        org = self.config.get_sonarcloud_org()
        patterns = [
            f"{owner}_{repo}",
            f"{repo}",
            f"{owner.replace('-', '_')}_{repo.replace('-', '_')}",
        ]

        if org:
            patterns.extend([
                f"{org}_{repo}",
                f"{org}:{repo}",
            ])

        return patterns


async def fetch_all_repos(
    config: Config,
    check_sonar: bool = False,
    progress_callback=None,
    limit: int = 0
) -> List[RepoOverview]:
    """Fetch all repository data asynchronously.

    Args:
        config: Configuration object
        check_sonar: Whether to check SonarCloud status
        progress_callback: Optional async callback(current, total, repo_name)
        limit: Max repos to fetch (0 = unlimited, for debugging)
    """
    github = GitHubClient(config)
    sonar = SonarCloudClient(config)

    repos = await github.get_user_repos()
    overviews = []

    # Filter excluded repos first for accurate count
    repos = [r for r in repos if not config.is_excluded(r["name"])]

    # Debug limit
    if limit > 0:
        repos = repos[:limit]

    total = len(repos)

    for i, repo_data in enumerate(repos):
        repo_name = repo_data["name"]
        owner = repo_data["owner"]["login"]

        if progress_callback:
            await progress_callback(i + 1, total, repo_name)

        # Get issues
        issues = []
        if repo_data.get("hasIssuesEnabled", True):
            issues = await github.get_repo_issues(owner, repo_name)

        # Get SonarCloud status if requested
        sonar_status = None
        if check_sonar:
            project_keys = sonar.guess_project_key(owner, repo_name)
            for project_key in project_keys:
                sonar_status = await sonar.get_project_status(project_key)
                if sonar_status:
                    break

        # Check local path
        local_path = github.get_local_repo_path(repo_name)

        overviews.append(RepoOverview(
            name=repo_name,
            owner=owner,
            url=repo_data["url"],
            open_issues_count=len(issues),
            issues=issues,
            sonar_status=sonar_status,
            local_path=str(local_path) if local_path else None
        ))

    return overviews
