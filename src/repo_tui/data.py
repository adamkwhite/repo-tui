"""Data fetching clients for GitHub and SonarCloud."""

from __future__ import annotations

import asyncio
import dataclasses
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, NamedTuple

from .config import Config
from .models import Issue, PullRequest, RepoOverview, SonarStatus

if TYPE_CHECKING:
    pass

ProgressCallback = Callable[[int, int, str], Coroutine[Any, Any, None]]

CACHE_DIR = Path("~/.cache/repo-tui").expanduser()
CACHE_FILE = CACHE_DIR / "repos.json"

# Sentinel owner used for repos that exist locally but have no GitHub remote.
LOCAL_ONLY_OWNER = "local"

_GITHUB_ORIGIN_RE = re.compile(
    r"^(?:git@github\.com:|https?://(?:[^@/]+@)?github\.com/)([^/]+)/(.+?)(?:\.git)?/?$"
)


def parse_github_origin(origin: str) -> tuple[str, str] | None:
    """Parse a GitHub remote URL into (owner, repo) — preserves case.

    Returns None for non-GitHub URLs.
    """
    match = _GITHUB_ORIGIN_RE.match(origin.strip())
    if not match:
        return None
    return match.group(1), match.group(2)


class NetworkError(Exception):
    """Raised when GitHub API calls fail due to network issues."""


class FetchResult(NamedTuple):
    """Result of fetch_all_repos with cache metadata."""

    repos: list[RepoOverview]
    is_cached: bool
    cache_timestamp: str | None


def save_cache(repos: list[RepoOverview]) -> None:
    """Write repos to local cache with timestamp."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "timestamp": datetime.now(UTC).isoformat(),
        "repos": [dataclasses.asdict(r) for r in repos],
    }
    CACHE_FILE.write_text(json.dumps(payload, default=str))


def load_cache() -> tuple[list[RepoOverview], str] | None:
    """Load cached repos. Returns (repos, timestamp_str) or None."""
    if not CACHE_FILE.exists():
        return None
    try:
        data = json.loads(CACHE_FILE.read_text())
        repos = [_dict_to_repo(r) for r in data["repos"]]
        return repos, data["timestamp"]
    except Exception:
        return None


def _dict_to_repo(d: dict) -> RepoOverview:
    """Reconstruct a RepoOverview from a dict."""
    issues = [Issue(**i) for i in d.get("issues", [])]
    prs = [PullRequest(**p) for p in d["pull_requests"]] if d.get("pull_requests") else None
    sonar = SonarStatus(**d["sonar_status"]) if d.get("sonar_status") else None
    return RepoOverview(
        name=d["name"],
        owner=d["owner"],
        url=d["url"],
        open_issues_count=d["open_issues_count"],
        issues=issues,
        sonar_status=sonar,
        is_private=d.get("is_private", False),
        local_path=d.get("local_path"),
        sonar_checked=d.get("sonar_checked", False),
        language=d.get("language"),
        topics=d.get("topics"),
        pull_requests=prs,
        details_loaded=d.get("details_loaded", False),
        has_uncommitted_changes=d.get("has_uncommitted_changes", False),
        current_branch=d.get("current_branch"),
        description=d.get("description"),
        friendly_name=d.get("friendly_name"),
        pushed_at=d.get("pushed_at"),
        fetch_failed=d.get("fetch_failed", False),
        sonar_unreachable=d.get("sonar_unreachable", False),
    )


async def _git_origin_url(repo_path: Path) -> str | None:
    """Return the origin remote URL for a local git repo, or None if not set."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "git",
            "-C",
            str(repo_path),
            "remote",
            "get-url",
            "origin",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        if proc.returncode != 0:
            return None
        url = stdout.decode().strip()
        return url or None
    except Exception:
        return None


async def _git_last_commit_iso(repo_path: Path) -> str | None:
    """Return the ISO 8601 commit date of HEAD, or None on error."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "git",
            "-C",
            str(repo_path),
            "log",
            "-1",
            "--format=%cI",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        if proc.returncode != 0:
            return None
        value = stdout.decode().strip()
        return value or None
    except Exception:
        return None


class LocalRepoScan(NamedTuple):
    """Result of scanning the local code path for git repos."""

    by_owner_repo: dict[tuple[str, str], Path]
    local_only: list[Path]


async def scan_local_repos(local_code_path: Path) -> LocalRepoScan:
    """Scan the local code path for git repositories.

    Returns:
        LocalRepoScan with:
        - by_owner_repo: maps (owner_lower, name_lower) -> local path for repos
          whose origin points at a GitHub URL. Used to find local checkouts even
          when the directory name differs from the GitHub repo name.
        - local_only: paths for repos with no remote, or with a non-GitHub remote.
    """
    scan = LocalRepoScan(by_owner_repo={}, local_only=[])
    if not local_code_path.exists() or not local_code_path.is_dir():
        return scan

    candidates = [
        entry for entry in local_code_path.iterdir() if entry.is_dir() and (entry / ".git").exists()
    ]
    if not candidates:
        return scan

    origins = await asyncio.gather(*(_git_origin_url(p) for p in candidates))

    for path, origin in zip(candidates, origins, strict=True):
        parsed = parse_github_origin(origin) if origin else None
        if parsed:
            owner, name = parsed
            scan.by_owner_repo[(owner.lower(), name.lower())] = path
        else:
            scan.local_only.append(path)

    return scan


def format_cache_age(timestamp: str | None) -> str:
    """Format a cache timestamp as relative time."""
    if not timestamp:
        return "unknown age"
    try:
        cached_time = datetime.fromisoformat(timestamp)
        delta = datetime.now(UTC) - cached_time
        minutes = int(delta.total_seconds() // 60)
        if minutes < 1:
            return "just now"
        if minutes < 60:
            return f"{minutes}m ago"
        hours = minutes // 60
        if hours < 24:
            return f"{hours}h ago"
        days = hours // 24
        return f"{days}d ago"
    except (ValueError, AttributeError):
        return "unknown age"


def summarize_checks(rollup: Any) -> str | None:
    """Collapse a gh `statusCheckRollup` blob into SUCCESS / FAILURE / PENDING.

    gh returns either a dict with "contexts" or a bare list of contexts
    depending on the query, and individual contexts report their result as
    either "state" (status checks) or "conclusion" (check runs).
    """
    contexts: list[Any] = []
    if isinstance(rollup, dict):
        contexts = rollup.get("contexts", []) or []
    elif isinstance(rollup, list):
        contexts = rollup
    if not contexts:
        return None

    statuses = [c.get("state") or c.get("conclusion") for c in contexts if isinstance(c, dict)]
    if any(s in ("FAILURE", "failure", "TIMED_OUT") for s in statuses):
        return "FAILURE"
    if any(s in ("PENDING", "pending", "IN_PROGRESS") for s in statuses):
        return "PENDING"
    non_empty = [s for s in statuses if s]
    if non_empty and all(s in ("SUCCESS", "success") for s in non_empty):
        return "SUCCESS"
    return None


def _parse_pr(pr: dict[str, Any]) -> PullRequest:
    """Build a PullRequest from one entry of `gh pr list --json`."""
    reviewers = [r.get("login") for r in pr.get("reviewRequests", []) if r.get("login")]
    author = pr.get("author", {})
    return PullRequest(
        number=pr["number"],
        title=pr["title"],
        url=pr["url"],
        author=author.get("login", "unknown"),
        state=pr["state"],
        draft=pr.get("isDraft", False),
        labels=[label["name"] for label in pr.get("labels", [])],
        body=pr.get("body", ""),
        reviewers=reviewers or None,
        review_decision=pr.get("reviewDecision"),
        head_ref=pr.get("headRefName"),
        base_ref=pr.get("baseRefName"),
        created_at=pr.get("createdAt"),
        updated_at=pr.get("updatedAt"),
        mergeable=pr.get("mergeable"),
        checks_status=summarize_checks(pr.get("statusCheckRollup")),
        author_name=author.get("name"),  # Full name, may be absent
    )


def _parse_issue(issue: dict[str, Any]) -> Issue:
    """Build an Issue from one entry of `gh issue list --json`."""
    assignees = issue.get("assignees")
    return Issue(
        number=issue["number"],
        title=issue["title"],
        url=issue["url"],
        labels=[label["name"] for label in issue.get("labels", [])],
        state=issue["state"],
        body=issue.get("body", "") or "",
        assignee=assignees[0].get("login") if assignees else None,
    )


class SonarCheck(NamedTuple):
    """Outcome of looking a repo up in Sonar."""

    status: SonarStatus | None
    checked: bool
    unreachable: bool


async def check_sonar_status(
    config: Config, sonar: SonarCloudClient, owner: str, repo_name: str
) -> SonarCheck:
    """Try each candidate project key until one answers.

    Stops at the first NetworkError: if the instance is unreachable, the
    remaining key spellings just repeat the same timeout.
    """
    project_keys = sonar.guess_project_key(owner, repo_name)
    config.debug_log(
        "sonar-check",
        f"\n=== Checking sonar for {repo_name} ===\nProject keys to try: {project_keys}\n",
    )

    for project_key in project_keys:
        try:
            status = await sonar.get_project_status(project_key)
        except NetworkError:
            return SonarCheck(None, checked=True, unreachable=True)
        config.debug_log("sonar-check", f"Tried {project_key}: {status}\n")
        if status:
            return SonarCheck(status, checked=True, unreachable=False)

    config.debug_log("sonar-check", f"Final: checked=True, status=None ({repo_name})\n")
    return SonarCheck(None, checked=True, unreachable=False)


class GitHubClient:
    """GitHub API client using gh CLI."""

    def __init__(self, config: Config) -> None:
        self.config = config

    def _debug(self, message: str) -> None:
        """Append to the PR fetch debug log, but only when debug is enabled."""
        self.config.debug_log("pr-fetch", message)

    async def get_user_repos(self) -> list[dict[str, Any]]:
        """Get all repositories for the authenticated user or organization."""
        try:
            # Build command based on whether github_org is set
            cmd = ["gh", "repo", "list"]

            # If github_org is configured, list repos from that org
            github_org = self.config.data.get("github_org")
            if github_org:
                cmd.append(github_org)

            cmd.extend(
                [
                    "--json",
                    "name,owner,url,hasIssuesEnabled,primaryLanguage,repositoryTopics,description,pushedAt,isPrivate",
                    "--limit",
                    "1000",
                ]
            )

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()

            if proc.returncode != 0:
                raise NetworkError(f"gh repo list failed (exit {proc.returncode})")

            repos: list[dict[str, Any]] = json.loads(stdout.decode())
            for repo in repos:
                repo["openIssuesCount"] = 0
            return repos
        except NetworkError:
            raise
        except Exception as e:
            raise NetworkError(str(e)) from e

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
            stdout, stderr = await proc.communicate()

            if proc.returncode != 0:
                raise NetworkError(
                    f"gh issue list failed for {owner}/{repo} "
                    f"(exit {proc.returncode}): {stderr.decode().strip()}"
                )

            issues_data = json.loads(stdout.decode())
            return [_parse_issue(issue) for issue in issues_data if issue["state"] == "OPEN"]
        except NetworkError:
            raise
        except Exception as e:
            raise NetworkError(f"could not read issues for {owner}/{repo}: {e}") from e

    async def get_repo_prs(self, owner: str, repo: str) -> list[PullRequest]:
        """Get open pull requests for a repository."""
        self._debug(f"\n=== Fetching PRs for {owner}/{repo} ===\n")

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
            stdout, stderr = await proc.communicate()

            self._debug(f"Return code: {proc.returncode}\nStdout length: {len(stdout)}\n")

            if proc.returncode != 0:
                raise NetworkError(
                    f"gh pr list failed for {owner}/{repo} "
                    f"(exit {proc.returncode}): {stderr.decode().strip()}"
                )

            prs_data = json.loads(stdout.decode())
            self._debug(f"Parsed {len(prs_data)} PRs from JSON\n")

            result = [_parse_pr(pr) for pr in prs_data]

            self._debug(f"Returning {len(result)} PRs\n")

            return result
        except NetworkError:
            raise
        except Exception as e:
            import traceback

            self._debug(
                f"\n=== ERROR fetching PRs for {owner}/{repo} ===\n"
                f"Error: {e}\n{traceback.format_exc()}\n"
            )
            raise NetworkError(f"could not read PRs for {owner}/{repo}: {e}") from e

    def get_local_repo_path(self, repo_name: str) -> Path | None:
        """Check if repo exists locally and return path."""
        local_path = self.config.get_local_code_path() / repo_name
        if local_path.exists() and local_path.is_dir():
            return local_path
        return None

    async def get_git_status(self, repo_path: Path) -> tuple[bool | None, str | None]:
        """Check if repo has uncommitted changes and get current branch.

        Returns:
            tuple: (has_uncommitted_changes, current_branch), where
            has_uncommitted_changes is None when git could not be run at all.
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
                # None, not False: a git that failed to run tells us nothing about
                # the working tree, and False renders as a clean repo.
                return (None, None)

            # Only count modified/added/deleted tracked files, not untracked files (??)
            status_lines = stdout.decode().strip().split("\n")
            has_changes = any(line and not line.startswith("??") for line in status_lines)

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
            return (None, None)


class SonarCloudClient:
    """SonarCloud/SonarQube API client."""

    def __init__(self, config: Config) -> None:
        self.config = config
        # Use configured URL or default to public SonarCloud
        sonar_url = config.data.get("sonar_url")
        if sonar_url:
            # Self-hosted SonarQube
            self.base_url = f"{sonar_url.rstrip('/')}/api"
        else:
            # Public SonarCloud
            self.base_url = "https://sonarcloud.io/api"

        # Get token from config or pass
        self.token = config.get_sonar_token()

    async def get_project_status(self, project_key: str) -> SonarStatus | None:
        """Get quality gate status for a project."""
        try:
            url = f"{self.base_url}/qualitygates/project_status?projectKey={urllib.parse.quote(project_key)}"

            loop = asyncio.get_event_loop()
            data = await loop.run_in_executor(None, self._fetch_url, url)

            if data is None:
                return None

            project_status = data.get("projectStatus", {})

            # Build dashboard URL
            sonar_url = self.config.data.get("sonar_url")
            if sonar_url:
                dashboard_url = (
                    f"{sonar_url.rstrip('/')}/dashboard?id={urllib.parse.quote(project_key)}"
                )
            else:
                dashboard_url = (
                    f"https://sonarcloud.io/dashboard?id={urllib.parse.quote(project_key)}"
                )

            return SonarStatus(
                project_key=project_key,
                status=project_status.get("status", "NONE"),
                url=dashboard_url,
                conditions=project_status.get("conditions", []),
            )
        except NetworkError:
            raise
        except Exception:
            # Malformed payload for a project that does exist — treat as absent.
            return None

    def _fetch_url(self, url: str) -> dict[str, Any] | None:
        """Fetch URL and return JSON data.

        Returns None when Sonar answers "no such project" (404). Any other
        failure — timeout, 5xx, bad token, DNS — raises NetworkError, because
        "we could not ask" must not be reported as "no project here".
        """
        try:
            request = urllib.request.Request(url)

            # Add authentication header if token is provided
            if self.token:
                # SonarQube uses Basic auth with token as username and empty password
                import base64

                credentials = base64.b64encode(f"{self.token}:".encode()).decode()
                request.add_header("Authorization", f"Basic {credentials}")

            self.config.debug_log(
                "sonar-fetch", f"\nFetching: {url}\nHas token: {bool(self.token)}\n"
            )

            with urllib.request.urlopen(request, timeout=10) as response:
                data: dict[str, Any] = json.loads(response.read().decode())
                self.config.debug_log("sonar-fetch", f"Success: {data}\n")
                return data
        except urllib.error.HTTPError as e:
            self.config.debug_log("sonar-fetch", f"HTTP {e.code}: {e}\n")
            if e.code == 404:
                return None
            raise NetworkError(f"sonar request failed (HTTP {e.code})") from e
        except Exception as e:
            self.config.debug_log("sonar-fetch", f"Error: {e}\n")
            raise NetworkError(f"sonar request failed: {e}") from e

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


async def _build_local_only_overviews(
    config: Config,
    paths: list[Path],
) -> list[RepoOverview]:
    """Build RepoOverview entries for local repos that have no GitHub remote."""
    if not paths:
        return []

    github = GitHubClient(config)
    overviews: list[RepoOverview] = []

    async def build_one(path: Path) -> RepoOverview | None:
        name = path.name
        if not config.should_include_repo(name):
            return None
        has_uncommitted, current_branch = await github.get_git_status(path)
        pushed_at = await _git_last_commit_iso(path)
        return RepoOverview(
            name=name,
            owner=LOCAL_ONLY_OWNER,
            url="",
            open_issues_count=0,
            issues=[],
            sonar_status=None,
            local_path=str(path),
            sonar_checked=False,
            pull_requests=[],
            details_loaded=True,
            has_uncommitted_changes=has_uncommitted,
            current_branch=current_branch,
            friendly_name=config.get_friendly_name(name),
            pushed_at=pushed_at,
        )

    results = await asyncio.gather(*(build_one(p) for p in paths))
    overviews.extend(r for r in results if r is not None)
    return overviews


async def _fetch_issues_and_prs(
    github: GitHubClient, owner: str, repo_name: str, has_issues: bool = True
) -> tuple[list[Issue], list[PullRequest], bool]:
    """Fetch a repo's issues and PRs together. Returns (issues, prs, failed).

    A gh failure must not abort the whole sweep — one unreachable repo should
    not blank the other 149 — so failure is reported as a flag, and the caller
    marks the repo unknown rather than rendering empty lists as "clean".

    return_exceptions=True because with the default, the first failure
    propagates while the sibling task keeps running unawaited, and the
    resulting "exception was never retrieved" noise on stderr corrupts the TUI.
    """
    issues_task = (
        github.get_repo_issues(owner, repo_name) if has_issues else asyncio.sleep(0, result=[])
    )
    prs_task = github.get_repo_prs(owner, repo_name)

    issues_result, prs_result = await asyncio.gather(issues_task, prs_task, return_exceptions=True)

    failed = isinstance(issues_result, BaseException) or isinstance(prs_result, BaseException)
    issues = [] if isinstance(issues_result, BaseException) else issues_result
    prs = [] if isinstance(prs_result, BaseException) else prs_result
    return issues, prs, failed


async def _cached_result(config: Config, github: GitHubClient) -> FetchResult:
    """Serve the last good sweep when GitHub is unreachable.

    Git status is re-read for every local checkout: that works offline and is
    the part most likely to have changed since the cache was written.
    """
    cached = load_cache()
    if not cached:
        return FetchResult(repos=[], is_cached=True, cache_timestamp=None)

    cached_repos, timestamp = cached
    cached_repos = [r for r in cached_repos if config.should_include_repo(r.name)]
    cached_repos.sort(key=lambda r: r.pushed_at or "", reverse=True)

    for repo in cached_repos:
        local_path = Path(repo.local_path) if repo.local_path else None
        if local_path and local_path.exists():
            repo.has_uncommitted_changes, repo.current_branch = await github.get_git_status(
                local_path
            )

    return FetchResult(repos=cached_repos, is_cached=True, cache_timestamp=timestamp)


async def fetch_all_repos(
    config: Config,
    check_sonar: bool = False,
    progress_callback: ProgressCallback | None = None,
    limit: int = 0,
) -> FetchResult:
    """Fetch all repository data asynchronously.

    Args:
        config: Configuration object
        check_sonar: Whether to check SonarCloud status
        progress_callback: Optional async callback(current, total, repo_name)
        limit: Max repos to fetch (0 = unlimited, for debugging)

    Returns:
        FetchResult with repos, is_cached flag, and cache timestamp.
    """
    github = GitHubClient(config)
    sonar = SonarCloudClient(config)

    try:
        repos = await github.get_user_repos()
    except NetworkError:
        return await _cached_result(config, github)

    overviews: list[RepoOverview] = []

    repos = [r for r in repos if config.should_include_repo(r["name"])]

    if limit > 0:
        repos = repos[:limit]

    total = len(repos)

    # Scan local code path once: lets us match a checkout to its remote even when
    # the directory name differs from the GitHub repo name (e.g. local
    # "kafka-food-pipeline" -> remote "KafkaFoodPipeline"), and surface dirs
    # whose origin isn't on GitHub at all.
    local_scan = await scan_local_repos(config.get_local_code_path())

    # Parallel fetch: create tasks for all repos
    async def fetch_repo_data(repo_data: dict[str, Any]) -> RepoOverview:
        repo_name = repo_data["name"]
        owner = repo_data["owner"]["login"]

        issues, pull_requests, fetch_failed = await _fetch_issues_and_prs(
            github, owner, repo_name, has_issues=repo_data.get("hasIssuesEnabled", True)
        )

        local_path = local_scan.by_owner_repo.get((owner.lower(), repo_name.lower()))
        if local_path is None:
            # Fall back to directory-name match for repos with no remote URL set.
            local_path = github.get_local_repo_path(repo_name)
        primary_lang = repo_data.get("primaryLanguage")
        language = primary_lang.get("name") if primary_lang else None
        topics_data = repo_data.get("repositoryTopics", [])
        topics = [t["name"] for t in topics_data] if topics_data else None
        description = repo_data.get("description")
        pushed_at = repo_data.get("pushedAt")

        # Check git status if repo is local
        has_uncommitted: bool | None = False
        current_branch = None
        if local_path:
            has_uncommitted, current_branch = await github.get_git_status(local_path)

        sonar_result = (
            await check_sonar_status(config, sonar, owner, repo_name)
            if check_sonar
            else SonarCheck(None, checked=False, unreachable=False)
        )

        return RepoOverview(
            name=repo_name,
            owner=owner,
            url=repo_data["url"],
            open_issues_count=len(issues),
            issues=issues,
            sonar_status=sonar_result.status,
            is_private=repo_data.get("isPrivate", False),
            local_path=str(local_path) if local_path else None,
            sonar_checked=sonar_result.checked,
            language=language,
            topics=topics,
            pull_requests=pull_requests,
            details_loaded=True,
            has_uncommitted_changes=has_uncommitted,
            current_branch=current_branch,
            description=description,
            friendly_name=config.get_friendly_name(repo_name),
            pushed_at=pushed_at,
            fetch_failed=fetch_failed,
            sonar_unreachable=sonar_result.unreachable,
        )

    # Process in batches to avoid overwhelming the API
    batch_size = 10
    for i in range(0, total, batch_size):
        batch = repos[i : i + batch_size]
        if progress_callback:
            await progress_callback(i + len(batch), total, f"batch {i // batch_size + 1}")

        batch_results = await asyncio.gather(*[fetch_repo_data(r) for r in batch])
        overviews.extend(batch_results)

    # Add local-only repos (dirs with no GitHub remote) so they show up alongside
    # GitHub-backed repos. They have no issues/PRs/Sonar — just git status.
    local_only_overviews = await _build_local_only_overviews(config, local_scan.local_only)
    overviews.extend(local_only_overviews)

    # Sort by most recently pushed first
    overviews.sort(key=lambda r: r.pushed_at or "", reverse=True)

    # Save to cache on successful fetch
    save_cache(overviews)

    return FetchResult(repos=overviews, is_cached=False, cache_timestamp=None)


async def fetch_single_repo(
    config: Config,
    owner: str,
    repo_name: str,
    check_sonar: bool = False,
    local_path: Path | None = None,
    is_private: bool = False,
) -> RepoOverview:
    """Fetch data for a single repository.

    Args:
        config: Configuration object
        owner: Repository owner (use LOCAL_ONLY_OWNER for local-only repos)
        repo_name: Repository name
        check_sonar: Whether to check SonarCloud status
        local_path: Override for the local checkout path. Required when
            owner == LOCAL_ONLY_OWNER (since the directory name may differ
            from anything on GitHub).
    """
    github = GitHubClient(config)
    sonar = SonarCloudClient(config)

    if owner == LOCAL_ONLY_OWNER:
        return await _local_only_overview(config, github, repo_name, local_path, is_private)

    issues, pull_requests, fetch_failed = await _fetch_issues_and_prs(github, owner, repo_name)

    sonar_result = (
        await check_sonar_status(config, sonar, owner, repo_name)
        if check_sonar
        else SonarCheck(None, checked=False, unreachable=False)
    )

    if local_path is None:
        local_path = github.get_local_repo_path(repo_name)

    # Check git status if repo is local
    has_uncommitted: bool | None = False
    current_branch = None
    if local_path:
        has_uncommitted, current_branch = await github.get_git_status(local_path)

    return RepoOverview(
        name=repo_name,
        owner=owner,
        url=f"https://github.com/{owner}/{repo_name}",
        open_issues_count=len(issues),
        issues=issues,
        sonar_status=sonar_result.status,
        is_private=is_private,
        local_path=str(local_path) if local_path else None,
        sonar_checked=check_sonar,
        pull_requests=pull_requests,
        details_loaded=True,
        has_uncommitted_changes=has_uncommitted,
        current_branch=current_branch,
        friendly_name=config.get_friendly_name(repo_name),
        fetch_failed=fetch_failed,
        sonar_unreachable=sonar_result.unreachable,
    )


async def _local_only_overview(
    config: Config,
    github: GitHubClient,
    repo_name: str,
    local_path: Path | None,
    is_private: bool,
) -> RepoOverview:
    """Overview for a checkout with no GitHub remote: git status and nothing else."""
    path = local_path or github.get_local_repo_path(repo_name)
    has_uncommitted: bool | None = False
    current_branch = None
    pushed_at = None
    if path:
        has_uncommitted, current_branch = await github.get_git_status(path)
        pushed_at = await _git_last_commit_iso(path)

    return RepoOverview(
        name=repo_name,
        owner=LOCAL_ONLY_OWNER,
        url="",
        open_issues_count=0,
        issues=[],
        sonar_status=None,
        is_private=is_private,
        local_path=str(path) if path else None,
        sonar_checked=False,
        pull_requests=[],
        details_loaded=True,
        has_uncommitted_changes=has_uncommitted,
        current_branch=current_branch,
        friendly_name=config.get_friendly_name(repo_name),
        pushed_at=pushed_at,
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

    if repo.owner == LOCAL_ONLY_OWNER:
        # Local-only repos have no issues/PRs to fetch.
        repo.issues = []
        repo.pull_requests = []
        repo.open_issues_count = 0
        repo.details_loaded = True
        return

    github = GitHubClient(config)

    try:
        issues = await github.get_repo_issues(repo.owner, repo.name)
        pull_requests = await github.get_repo_prs(repo.owner, repo.name)
    except NetworkError:
        # Leave details_loaded False so expanding again retries the fetch.
        repo.fetch_failed = True
        return

    repo.issues = issues
    repo.open_issues_count = len(issues)
    repo.pull_requests = pull_requests
    repo.details_loaded = True
    repo.fetch_failed = False
