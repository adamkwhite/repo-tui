"""A failed gh call must not render as a clean repo.

Before this, get_repo_issues / get_repo_prs returned [] on any failure, so an
auth error or a network drop produced open_issues_count=0 and pull_requests=[]
- exactly the shape of a healthy repo, which the status dot paints green.
"""

from __future__ import annotations

import json
import urllib.error
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from repo_tui.config import Config
from repo_tui.data import (
    GitHubClient,
    NetworkError,
    fetch_all_repos,
    fetch_repo_details,
)
from repo_tui.dependabot import merge_all_dependabot_prs
from repo_tui.models import RepoOverview
from repo_tui.widgets.repo_list import RepoListWidget


def _config(local_path: Path) -> Config:
    cfg_path = local_path / ".repo-overview.json"
    cfg_path.write_text(
        json.dumps(
            {
                "included_repos": [],
                "excluded_repos": [],
                "local_code_path": str(local_path),
                "friendly_names": {},
            }
        )
    )
    return Config(str(cfg_path))


def _gh_repo(name: str = "widget-api", owner: str = "adamkwhite") -> dict:
    return {
        "name": name,
        "owner": {"login": owner},
        "url": f"https://github.com/{owner}/{name}",
        "hasIssuesEnabled": True,
        "primaryLanguage": None,
        "repositoryTopics": [],
        "description": None,
        "pushedAt": "2026-01-01T00:00:00Z",
    }


class _FakeProc:
    def __init__(self, returncode: int, stdout: bytes = b"", stderr: bytes = b"") -> None:
        self.returncode = returncode
        self._stdout = stdout
        self._stderr = stderr

    async def communicate(self) -> tuple[bytes, bytes]:
        return self._stdout, self._stderr


# ---------- client raises instead of swallowing ----------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["get_repo_issues", "get_repo_prs"])
async def test_client_raises_on_gh_failure(tmp_path: Path, method: str) -> None:
    client = GitHubClient(_config(tmp_path))
    proc = _FakeProc(1, stderr=b"gh: authentication required")

    with (
        patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as spawn,
        pytest.raises(NetworkError, match="authentication required"),
    ):
        spawn.return_value = proc
        await getattr(client, method)("adamkwhite", "widget-api")


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["get_repo_issues", "get_repo_prs"])
async def test_client_raises_on_malformed_json(tmp_path: Path, method: str) -> None:
    client = GitHubClient(_config(tmp_path))
    proc = _FakeProc(0, stdout=b"not json at all")

    with (
        patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as spawn,
        pytest.raises(NetworkError),
    ):
        spawn.return_value = proc
        await getattr(client, method)("adamkwhite", "widget-api")


@pytest.mark.asyncio
async def test_pr_debug_log_not_written_when_debug_disabled(tmp_path: Path) -> None:
    """Debug logging is opt-in; the old code wrote to /tmp on every fetch."""
    client = GitHubClient(_config(tmp_path))
    proc = _FakeProc(0, stdout=b"[]")

    with (
        patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as spawn,
        patch("builtins.open") as fake_open,
    ):
        spawn.return_value = proc
        assert await client.get_repo_prs("adamkwhite", "widget-api") == []

    fake_open.assert_not_called()


# ---------- fetch marks the repo instead of reporting it clean -------------------


@pytest.mark.asyncio
async def test_fetch_all_repos_marks_failed_repo(tmp_path: Path) -> None:
    config = _config(tmp_path)

    with (
        patch("repo_tui.data.GitHubClient.get_user_repos", new_callable=AsyncMock) as gh,
        patch("repo_tui.data.GitHubClient.get_repo_issues", new_callable=AsyncMock) as issues,
        patch("repo_tui.data.GitHubClient.get_repo_prs", new_callable=AsyncMock) as prs,
        patch("repo_tui.data.save_cache"),
    ):
        gh.return_value = [_gh_repo()]
        issues.side_effect = NetworkError("gh issue list failed")
        prs.return_value = []

        result = await fetch_all_repos(config)

    assert len(result.repos) == 1
    assert result.repos[0].fetch_failed is True


@pytest.mark.asyncio
async def test_fetch_all_repos_one_failure_does_not_sink_the_others(tmp_path: Path) -> None:
    """A single unreachable repo must not blank out the rest of the sweep."""
    config = _config(tmp_path)

    async def issues_by_repo(_owner: str, repo: str) -> list:
        if repo == "broken":
            raise NetworkError("gh issue list failed")
        return []

    with (
        patch("repo_tui.data.GitHubClient.get_user_repos", new_callable=AsyncMock) as gh,
        patch("repo_tui.data.GitHubClient.get_repo_issues", side_effect=issues_by_repo),
        patch("repo_tui.data.GitHubClient.get_repo_prs", new_callable=AsyncMock) as prs,
        patch("repo_tui.data.save_cache"),
    ):
        gh.return_value = [_gh_repo("broken"), _gh_repo("healthy")]
        prs.return_value = []

        result = await fetch_all_repos(config)

    by_name = {r.name: r for r in result.repos}
    assert by_name["broken"].fetch_failed is True
    assert by_name["healthy"].fetch_failed is False


@pytest.mark.asyncio
async def test_fetch_repo_details_leaves_room_to_retry(tmp_path: Path) -> None:
    repo = RepoOverview(
        name="widget-api",
        owner="adamkwhite",
        url="https://github.com/adamkwhite/widget-api",
        open_issues_count=0,
        issues=[],
        sonar_status=None,
    )

    with patch(
        "repo_tui.data.GitHubClient.get_repo_issues",
        new_callable=AsyncMock,
    ) as issues:
        issues.side_effect = NetworkError("gh issue list failed")
        await fetch_repo_details(_config(tmp_path), repo)

    assert repo.fetch_failed is True
    # Still unloaded, so expanding the row again re-fetches rather than
    # cementing the empty state.
    assert repo.details_loaded is False


# ---------- the status dot -------------------------------------------------------


def test_failed_repo_does_not_render_as_clean() -> None:
    widget = RepoListWidget()
    failed = RepoOverview(
        name="widget-api",
        owner="adamkwhite",
        url="https://github.com/adamkwhite/widget-api",
        open_issues_count=0,
        issues=[],
        sonar_status=None,
        fetch_failed=True,
    )

    rendered = str(widget._build_repo_option(failed).prompt)

    assert "[green]●[/green]" not in rendered
    assert "fetch failed" in rendered


# ---------- git status: unknown is not clean -------------------------------------


@pytest.mark.asyncio
async def test_git_status_unknown_when_git_fails(tmp_path: Path) -> None:
    client = GitHubClient(_config(tmp_path))

    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as spawn:
        spawn.return_value = _FakeProc(128, stderr=b"fatal: not a git repository")
        has_changes, branch = await client.get_git_status(tmp_path)

    # None, not False — False is indistinguishable from a clean tree.
    assert has_changes is None
    assert branch is None


def test_unknown_git_status_does_not_render_as_clean(tmp_path: Path) -> None:
    widget = RepoListWidget()
    repo = RepoOverview(
        name="widget-api",
        owner="adamkwhite",
        url="https://github.com/adamkwhite/widget-api",
        open_issues_count=0,
        issues=[],
        sonar_status=None,
        local_path=str(tmp_path),
        has_uncommitted_changes=None,
    )

    rendered = str(widget._build_repo_option(repo).prompt)

    assert "[green]●[/green]" not in rendered
    assert "git status unknown" in rendered


# ---------- sonar: unreachable is not "no project" -------------------------------


def test_sonar_404_means_no_project(tmp_path: Path) -> None:
    """A 404 is a real answer: this project does not exist."""
    from repo_tui.data import SonarCloudClient

    client = SonarCloudClient(_config(tmp_path))
    err = urllib.error.HTTPError("https://sonarcloud.io", 404, "Not Found", {}, None)  # type: ignore[arg-type]

    with patch("urllib.request.urlopen", side_effect=err):
        assert client._fetch_url("https://sonarcloud.io/api/x") is None


@pytest.mark.parametrize(
    "error",
    [
        urllib.error.HTTPError("https://sonarcloud.io", 503, "Service Unavailable", {}, None),  # type: ignore[arg-type]
        urllib.error.URLError("timed out"),
    ],
)
def test_sonar_transport_failure_raises(tmp_path: Path, error: Exception) -> None:
    from repo_tui.data import SonarCloudClient

    client = SonarCloudClient(_config(tmp_path))

    with patch("urllib.request.urlopen", side_effect=error), pytest.raises(NetworkError):
        client._fetch_url("https://sonarcloud.io/api/x")


@pytest.mark.asyncio
async def test_unreachable_sonar_is_not_reported_as_no_project(tmp_path: Path) -> None:
    config = _config(tmp_path)

    with (
        patch("repo_tui.data.GitHubClient.get_user_repos", new_callable=AsyncMock) as gh,
        patch("repo_tui.data.GitHubClient.get_repo_issues", new_callable=AsyncMock) as issues,
        patch("repo_tui.data.GitHubClient.get_repo_prs", new_callable=AsyncMock) as prs,
        patch("repo_tui.data.SonarCloudClient.get_project_status", new_callable=AsyncMock) as sonar,
        patch("repo_tui.data.save_cache"),
    ):
        gh.return_value = [_gh_repo()]
        issues.return_value = []
        prs.return_value = []
        sonar.side_effect = NetworkError("sonar request failed: timed out")

        result = await fetch_all_repos(config, check_sonar=True)

    repo = result.repos[0]
    assert repo.sonar_unreachable is True
    # One attempt, not one per candidate key spelling.
    assert sonar.await_count == 1

    rendered = str(RepoListWidget()._build_repo_option(repo).prompt)
    assert "No Sonar" not in rendered
    assert "Sonar unreachable" in rendered


# ---------- dependabot -----------------------------------------------------------


@pytest.mark.asyncio
async def test_dependabot_reports_unreadable_repo() -> None:
    """gh failing to list PRs must not be reported as 'no open Dependabot PRs'."""
    repo = RepoOverview(
        name="widget-api",
        owner="adamkwhite",
        url="https://github.com/adamkwhite/widget-api",
        open_issues_count=0,
        issues=[],
        sonar_status=None,
        pull_requests=[],
    )
    # Cached PR list must look like it has a Dependabot PR, or the fast path
    # skips the repo before it ever calls gh.
    from repo_tui.models import PullRequest

    repo.pull_requests = [
        PullRequest(
            number=1,
            title="bump requests",
            url="",
            author="app/dependabot",
            state="OPEN",
        )
    ]

    with patch(
        "repo_tui.dependabot._list_dependabot_prs",
        new_callable=AsyncMock,
    ) as listing:
        listing.return_value = None  # listing failed
        done = [p async for p in merge_all_dependabot_prs([repo]) if p.phase == "done"]

    assert len(done) == 1
    assert done[0].error is not None
    assert done[0].results == []
