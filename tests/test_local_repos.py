"""Tests for local repo scanning and local-only repo synthesis."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from repo_tui.config import Config
from repo_tui.data import (
    LOCAL_ONLY_OWNER,
    LocalRepoScan,
    fetch_all_repos,
    fetch_repo_details,
    fetch_single_repo,
    parse_github_origin,
    scan_local_repos,
)
from repo_tui.models import RepoOverview

# ---------- parse_github_origin --------------------------------------------------


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("git@github.com:adamkwhite/repo-tui.git", ("adamkwhite", "repo-tui")),
        ("git@github.com:adamkwhite/repo-tui", ("adamkwhite", "repo-tui")),
        ("https://github.com/adamkwhite/repo-tui.git", ("adamkwhite", "repo-tui")),
        ("https://github.com/adamkwhite/repo-tui", ("adamkwhite", "repo-tui")),
        ("https://github.com/adamkwhite/repo-tui/", ("adamkwhite", "repo-tui")),
        ("http://github.com/adamkwhite/repo-tui.git", ("adamkwhite", "repo-tui")),
        # Preserves case so we can present the canonical name back to users.
        ("git@github.com:adamkwhite/KafkaFoodPipeline.git", ("adamkwhite", "KafkaFoodPipeline")),
        # Token in URL.
        (
            "https://x-access-token:abc@github.com/adamkwhite/repo-tui.git",
            ("adamkwhite", "repo-tui"),
        ),
    ],
)
def test_parse_github_origin_valid(url: str, expected: tuple[str, str]) -> None:
    assert parse_github_origin(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "",
        "not-a-url",
        "git@gitlab.com:adamkwhite/repo-tui.git",
        "https://bitbucket.org/adamkwhite/repo-tui.git",
        "https://github.com/",
        "https://example.com/adamkwhite/repo-tui.git",
    ],
)
def test_parse_github_origin_rejects_non_github(url: str) -> None:
    assert parse_github_origin(url) is None


# ---------- scan_local_repos -----------------------------------------------------


def _git(repo: Path, *args: str) -> None:
    """Run a git command, swallowing output."""
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
    )


def _make_repo(parent: Path, name: str, origin: str | None = None) -> Path:
    """Create a real (tiny) git repo with optional origin remote."""
    path = parent / name
    path.mkdir()
    _git(path, "init", "-q", "-b", "main")
    _git(path, "config", "user.email", "test@example.com")
    _git(path, "config", "user.name", "Test")
    (path / "README.md").write_text("hi")
    _git(path, "add", "README.md")
    _git(path, "commit", "-q", "-m", "init")
    if origin:
        _git(path, "remote", "add", "origin", origin)
    return path


@pytest.mark.asyncio
async def test_scan_local_repos_empty_dir(tmp_path: Path) -> None:
    scan = await scan_local_repos(tmp_path)
    assert scan.by_owner_repo == {}
    assert scan.local_only == []


@pytest.mark.asyncio
async def test_scan_local_repos_missing_dir(tmp_path: Path) -> None:
    scan = await scan_local_repos(tmp_path / "nope")
    assert scan == LocalRepoScan(by_owner_repo={}, local_only=[])


@pytest.mark.asyncio
async def test_scan_local_repos_classifies_repos(tmp_path: Path) -> None:
    # Mismatched-name local checkout (the original bug).
    kafka = _make_repo(
        tmp_path,
        "kafka-food-pipeline",
        origin="git@github.com:adamkwhite/KafkaFoodPipeline.git",
    )
    # Normal local checkout.
    repo_tui = _make_repo(
        tmp_path,
        "repo-tui",
        origin="https://github.com/adamkwhite/repo-tui.git",
    )
    # Truly local-only (no remote at all).
    local_only = _make_repo(tmp_path, "flappy-bird", origin=None)
    # Non-GitHub remote — treat like local-only since we can't surface PRs/issues.
    gitlab_repo = _make_repo(
        tmp_path,
        "internal-tool",
        origin="git@gitlab.com:team/internal-tool.git",
    )
    # A non-git directory that should be ignored.
    (tmp_path / "not-a-repo").mkdir()
    (tmp_path / "not-a-repo" / "file.txt").write_text("x")

    scan = await scan_local_repos(tmp_path)

    assert scan.by_owner_repo == {
        ("adamkwhite", "kafkafoodpipeline"): kafka,
        ("adamkwhite", "repo-tui"): repo_tui,
    }
    assert sorted(scan.local_only) == sorted([local_only, gitlab_repo])


# ---------- fetch_all_repos integration ------------------------------------------


def _config(local_path: Path, included: list[str] | None = None) -> Config:
    """Build a Config pointing at a temp local code path."""
    cfg_data = {
        "included_repos": included or [],
        "excluded_repos": [],
        "local_code_path": str(local_path),
        "friendly_names": {},
    }
    cfg_path = local_path / ".repo-overview.json"
    cfg_path.write_text(json.dumps(cfg_data))
    return Config(str(cfg_path))


def _gh_repo(name: str, owner: str = "adamkwhite") -> dict:
    """Build a fake `gh repo list` JSON entry."""
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


@pytest.mark.asyncio
async def test_fetch_all_repos_matches_mismatched_local_dir(tmp_path: Path) -> None:
    """Local dir 'kafka-food-pipeline' should be matched to remote 'KafkaFoodPipeline'."""
    _make_repo(
        tmp_path,
        "kafka-food-pipeline",
        origin="git@github.com:adamkwhite/KafkaFoodPipeline.git",
    )
    config = _config(tmp_path)

    with (
        patch("repo_tui.data.GitHubClient.get_user_repos", new_callable=AsyncMock) as gh,
        patch("repo_tui.data.GitHubClient.get_repo_issues", new_callable=AsyncMock) as issues,
        patch("repo_tui.data.GitHubClient.get_repo_prs", new_callable=AsyncMock) as prs,
    ):
        gh.return_value = [_gh_repo("KafkaFoodPipeline")]
        issues.return_value = []
        prs.return_value = []

        result = await fetch_all_repos(config)

    assert len(result.repos) == 1
    repo = result.repos[0]
    assert repo.name == "KafkaFoodPipeline"
    assert repo.local_path == str(tmp_path / "kafka-food-pipeline")


@pytest.mark.asyncio
async def test_fetch_all_repos_synthesizes_local_only_repos(tmp_path: Path) -> None:
    _make_repo(tmp_path, "flappy-bird", origin=None)
    config = _config(tmp_path)

    with (
        patch("repo_tui.data.GitHubClient.get_user_repos", new_callable=AsyncMock) as gh,
        patch("repo_tui.data.GitHubClient.get_repo_issues", new_callable=AsyncMock) as issues,
        patch("repo_tui.data.GitHubClient.get_repo_prs", new_callable=AsyncMock) as prs,
        patch("repo_tui.data.save_cache"),
    ):
        gh.return_value = []
        issues.return_value = []
        prs.return_value = []

        result = await fetch_all_repos(config)

    assert len(result.repos) == 1
    local = result.repos[0]
    assert local.name == "flappy-bird"
    assert local.owner == LOCAL_ONLY_OWNER
    assert local.url == ""
    assert local.local_path == str(tmp_path / "flappy-bird")
    assert local.details_loaded is True
    assert local.pushed_at is not None  # derived from last commit


@pytest.mark.asyncio
async def test_fetch_all_repos_local_only_respects_included_filter(tmp_path: Path) -> None:
    _make_repo(tmp_path, "flappy-bird", origin=None)
    _make_repo(tmp_path, "menu-planner", origin=None)
    # Whitelist mode: only show flappy-bird.
    config = _config(tmp_path, included=["flappy-bird"])

    with (
        patch("repo_tui.data.GitHubClient.get_user_repos", new_callable=AsyncMock) as gh,
        patch("repo_tui.data.save_cache"),
    ):
        gh.return_value = []
        result = await fetch_all_repos(config)

    names = [r.name for r in result.repos]
    assert names == ["flappy-bird"]


# ---------- fetch_single_repo / fetch_repo_details -------------------------------


@pytest.mark.asyncio
async def test_fetch_single_repo_local_only_skips_github(tmp_path: Path) -> None:
    path = _make_repo(tmp_path, "flappy-bird", origin=None)
    config = _config(tmp_path)

    with (
        patch("repo_tui.data.GitHubClient.get_repo_issues", new_callable=AsyncMock) as issues,
        patch("repo_tui.data.GitHubClient.get_repo_prs", new_callable=AsyncMock) as prs,
    ):
        repo = await fetch_single_repo(
            config,
            owner=LOCAL_ONLY_OWNER,
            repo_name="flappy-bird",
            local_path=path,
        )

    issues.assert_not_called()
    prs.assert_not_called()
    assert repo.owner == LOCAL_ONLY_OWNER
    assert repo.local_path == str(path)
    assert repo.url == ""
    assert repo.details_loaded is True


@pytest.mark.asyncio
async def test_fetch_repo_details_local_only_no_op() -> None:
    config = Config.__new__(Config)  # bypass __init__
    config.data = {}
    repo = RepoOverview(
        name="flappy-bird",
        owner=LOCAL_ONLY_OWNER,
        url="",
        open_issues_count=0,
        issues=[],
        sonar_status=None,
        local_path="/tmp/flappy-bird",
        details_loaded=False,
    )

    with patch("repo_tui.data.GitHubClient.get_repo_issues", new_callable=AsyncMock) as issues:
        await fetch_repo_details(config, repo)

    issues.assert_not_called()
    assert repo.details_loaded is True
    assert repo.issues == []
    assert repo.pull_requests == []
