"""Data fetching clients for GitHub and SonarCloud."""

from __future__ import annotations

import asyncio
import json
import urllib.parse
import urllib.request
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .config import Config
from .models import Issue, PullRequest, RepoOverview, SonarStatus

if TYPE_CHECKING:
    pass

ProgressCallback = Callable[[int, int, str], Coroutine[Any, Any, None]]


class GitHubClient:
    """GitHub API client using gh CLI."""

    def __init__(self, config: Config) -> None:
        self.config = config

    async def get_user_repos(self) -> list[dict[str, Any]]:
        """Get all repositories for the authenticated user or organization."""
        try:
            # Build command based on whether github_org is set
            cmd = ["gh", "repo", "list"]

            # If github_org is configured, list repos from that org
            github_org = self.config.data.get("github_org")
            if github_org:
                cmd.append(github_org)

            cmd.extend([
                "--json",
                "name,owner,url,hasIssuesEnabled,primaryLanguage,repositoryTopics,description",
                "--limit",
                "1000",
            ])

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()

            if proc.returncode != 0:
                return []

            repos = json.loads(stdout.decode())
            for repo in repos:
                repo["openIssuesCount"] = 0
            return repos
        except Exception:
            return []

    async def get_repo_issues(self, owner: str, repo: str) -> list[Issue]:
        """Get open issues for a repository."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "gh",
                "issue",
                "list",
                "--repo",
                f"{owner}/{repo}",
                "--json",
                "number,title,url,labels,state,body,assignees",
                "--limit",
                "100",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()

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
                    assignee=(
                        issue.get("assignees", [{}])[0].get("login")
                        if issue.get("assignees")
                        else None
                    ),
                )
                for issue in issues_data
                if issue["state"] == "OPEN"
            ]
        except Exception:
            return []

    async def get_repo_prs(self, owner: str, repo: str) -> list[PullRequest]:
        """Get open pull requests for a repository."""
        # Debug: log that we're fetching
        with open("/tmp/pr-fetch-debug.log", "a") as f:
            f.write(f"\n=== Fetching PRs for {owner}/{repo} ===\n")

        try:
            proc = await asyncio.create_subprocess_exec(
                "gh",
                "pr",
                "list",
                "--repo",
                f"{owner}/{repo}",
                "--json",
                "number,title,url,author,state,isDraft,labels,body,reviewRequests,reviewDecision,headRefName,baseRefName,createdAt,updatedAt,mergeable,statusCheckRollup",
                "--limit",
                "100",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()

            with open("/tmp/pr-fetch-debug.log", "a") as f:
                f.write(f"Return code: {proc.returncode}\n")
                f.write(f"Stdout length: {len(stdout)}\n")

            if proc.returncode != 0:
                with open("/tmp/pr-fetch-debug.log", "a") as f:
                    f.write(f"Non-zero return code, returning empty\n")
                return []

            prs_data = json.loads(stdout.decode())
            with open("/tmp/pr-fetch-debug.log", "a") as f:
                f.write(f"Parsed {len(prs_data)} PRs from JSON\n")

            result = []

            for pr in prs_data:
                # Extract reviewers
                reviewers = [r.get("login") for r in pr.get("reviewRequests", []) if r.get("login")]

                # Extract checks status
                checks_rollup = pr.get("statusCheckRollup", {})
                checks_status = None
                if checks_rollup:
                    contexts = checks_rollup.get("contexts", [])
                    if contexts:
                        # Determine overall status
                        statuses = [c.get("state") or c.get("conclusion") for c in contexts]
                        if any(s in ["FAILURE", "failure", "TIMED_OUT"] for s in statuses):
                            checks_status = "FAILURE"
                        elif any(s in ["PENDING", "pending", "IN_PROGRESS"] for s in statuses):
                            checks_status = "PENDING"
                        elif all(s in ["SUCCESS", "success"] for s in statuses if s):
                            checks_status = "SUCCESS"

                result.append(PullRequest(
                    number=pr["number"],
                    title=pr["title"],
                    url=pr["url"],
                    author=pr.get("author", {}).get("login", "unknown"),
                    state=pr["state"],
                    draft=pr.get("isDraft", False),
                    labels=[label["name"] for label in pr.get("labels", [])],
                    body=pr.get("body", ""),
                    reviewers=reviewers if reviewers else None,
                    review_decision=pr.get("reviewDecision"),
                    head_ref=pr.get("headRefName"),
                    base_ref=pr.get("baseRefName"),
                    created_at=pr.get("createdAt"),
                    updated_at=pr.get("updatedAt"),
                    mergeable=pr.get("mergeable"),
                    checks_status=checks_status,
                ))

            with open("/tmp/pr-fetch-debug.log", "a") as f:
                f.write(f"Returning {len(result)} PRs\n")

            return result
        except Exception as e:
            # Debug: log the error to file
            with open("/tmp/pr-fetch-errors.log", "a") as f:
                import traceback
                f.write(f"\n=== ERROR fetching PRs for {owner}/{repo} ===\n")
                f.write(f"Error: {e}\n")
                f.write(traceback.format_exc())
                f.write("\n")
            return []

    def get_local_repo_path(self, repo_name: str) -> Path | None:
        """Check if repo exists locally and return path."""
        local_path = self.config.get_local_code_path() / repo_name
        if local_path.exists() and local_path.is_dir():
            return local_path
        return None

    async def get_git_status(self, repo_path: Path) -> tuple[bool, str | None]:
        """Check if repo has uncommitted changes and get current branch.

        Returns:
            tuple: (has_uncommitted_changes, current_branch)
        """
        try:
            # Check for uncommitted changes (ignoring untracked files)
            proc = await asyncio.create_subprocess_exec(
                "git",
                "-C",
                str(repo_path),
                "status",
                "--porcelain",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()

            if proc.returncode != 0:
                return (False, None)

            # Only count modified/added/deleted tracked files, not untracked files (??)
            status_lines = stdout.decode().strip().split('\n')
            has_changes = any(
                line and not line.startswith('??')
                for line in status_lines
            )

            # Get current branch
            proc = await asyncio.create_subprocess_exec(
                "git",
                "-C",
                str(repo_path),
                "rev-parse",
                "--abbrev-ref",
                "HEAD",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()

            if proc.returncode != 0:
                return (has_changes, None)

            current_branch = stdout.decode().strip()
            return (has_changes, current_branch)

        except Exception:
            return (False, None)


class SonarCloudClient:
    """SonarCloud API client for public projects."""

    BASE_URL = "https://sonarcloud.io/api"

    def __init__(self, config: Config) -> None:
        self.config = config

    async def get_project_status(self, project_key: str) -> SonarStatus | None:
        """Get quality gate status for a project."""
        try:
            url = f"{self.BASE_URL}/qualitygates/project_status?projectKey={urllib.parse.quote(project_key)}"

            loop = asyncio.get_event_loop()
            data = await loop.run_in_executor(None, self._fetch_url, url)

            if data is None:
                return None

            project_status = data.get("projectStatus", {})
            return SonarStatus(
                project_key=project_key,
                status=project_status.get("status", "NONE"),
                url=f"https://sonarcloud.io/dashboard?id={urllib.parse.quote(project_key)}",
                conditions=project_status.get("conditions", []),
            )
        except Exception:
            return None

    def _fetch_url(self, url: str) -> dict[str, Any] | None:
        """Fetch URL and return JSON data."""
        try:
            with urllib.request.urlopen(url, timeout=10) as response:
                return json.loads(response.read().decode())
        except Exception:
            return None

    def guess_project_key(self, owner: str, repo: str) -> list[str]:
        """Generate possible SonarCloud project keys."""
        org = self.config.get_sonarcloud_org()
        patterns = [
            f"{owner}_{repo}",
            f"{repo}",
            f"{owner.replace('-', '_')}_{repo.replace('-', '_')}",
        ]

        if org:
            patterns.extend(
                [
                    f"{org}_{repo}",
                    f"{org}:{repo}",
                ]
            )

        return patterns


async def fetch_all_repos(
    config: Config,
    check_sonar: bool = False,
    progress_callback: ProgressCallback | None = None,
    limit: int = 0,
) -> list[RepoOverview]:
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
    overviews: list[RepoOverview] = []

    repos = [r for r in repos if config.should_include_repo(r["name"])]

    if limit > 0:
        repos = repos[:limit]

    total = len(repos)

    # Parallel fetch: create tasks for all repos
    async def fetch_repo_data(repo_data: dict[str, Any]) -> RepoOverview:
        repo_name = repo_data["name"]
        owner = repo_data["owner"]["login"]

        # Fetch issues and PRs in parallel for this repo
        issues_task = github.get_repo_issues(owner, repo_name) if repo_data.get("hasIssuesEnabled", True) else asyncio.sleep(0, result=[])
        prs_task = github.get_repo_prs(owner, repo_name)

        issues, pull_requests = await asyncio.gather(issues_task, prs_task)

        local_path = github.get_local_repo_path(repo_name)
        primary_lang = repo_data.get("primaryLanguage")
        language = primary_lang.get("name") if primary_lang else None
        topics_data = repo_data.get("repositoryTopics", [])
        topics = [t["name"] for t in topics_data] if topics_data else None
        description = repo_data.get("description")

        # Check git status if repo is local
        has_uncommitted = False
        current_branch = None
        if local_path:
            has_uncommitted, current_branch = await github.get_git_status(local_path)

        return RepoOverview(
            name=repo_name,
            owner=owner,
            url=repo_data["url"],
            open_issues_count=len(issues),
            issues=issues,
            sonar_status=None,
            local_path=str(local_path) if local_path else None,
            sonar_checked=False,
            language=language,
            topics=topics,
            pull_requests=pull_requests,
            details_loaded=True,
            has_uncommitted_changes=has_uncommitted,
            current_branch=current_branch,
            description=description,
        )

    # Process in batches to avoid overwhelming the API
    batch_size = 10
    for i in range(0, total, batch_size):
        batch = repos[i:i + batch_size]
        if progress_callback:
            await progress_callback(i + len(batch), total, f"batch {i // batch_size + 1}")

        batch_results = await asyncio.gather(*[fetch_repo_data(r) for r in batch])
        overviews.extend(batch_results)

    return overviews


async def fetch_single_repo(
    config: Config,
    owner: str,
    repo_name: str,
    check_sonar: bool = False,
) -> RepoOverview:
    """Fetch data for a single repository.

    Args:
        config: Configuration object
        owner: Repository owner
        repo_name: Repository name
        check_sonar: Whether to check SonarCloud status
    """
    github = GitHubClient(config)
    sonar = SonarCloudClient(config)

    issues = await github.get_repo_issues(owner, repo_name)
    pull_requests = await github.get_repo_prs(owner, repo_name)

    sonar_status = None
    if check_sonar:
        project_keys = sonar.guess_project_key(owner, repo_name)
        for project_key in project_keys:
            sonar_status = await sonar.get_project_status(project_key)
            if sonar_status:
                break

    local_path = github.get_local_repo_path(repo_name)

    # Check git status if repo is local
    has_uncommitted = False
    current_branch = None
    if local_path:
        has_uncommitted, current_branch = await github.get_git_status(local_path)

    return RepoOverview(
        name=repo_name,
        owner=owner,
        url=f"https://github.com/{owner}/{repo_name}",
        open_issues_count=len(issues),
        issues=issues,
        sonar_status=sonar_status,
        local_path=str(local_path) if local_path else None,
        sonar_checked=check_sonar,
        pull_requests=pull_requests,
        details_loaded=True,
        has_uncommitted_changes=has_uncommitted,
        current_branch=current_branch,
    )


async def fetch_repo_details(
    config: Config,
    repo: RepoOverview,
) -> None:
    """Lazy-load issues and PRs for a repository (mutates repo in place).

    Args:
        config: Configuration object
        repo: Repository to load details for
    """
    if repo.details_loaded:
        return

    github = GitHubClient(config)

    issues = await github.get_repo_issues(repo.owner, repo.name)
    pull_requests = await github.get_repo_prs(repo.owner, repo.name)

    repo.issues = issues
    repo.open_issues_count = len(issues)
    repo.pull_requests = pull_requests
    repo.details_loaded = True
