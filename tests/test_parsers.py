"""The gh-payload parsers and status helpers pulled out of the fetch functions.

These were loop bodies inside `get_repo_prs` / `fetch_all_repos`, so exercising
one shape of `statusCheckRollup` previously meant mocking a subprocess.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from repo_tui.config import Config
from repo_tui.data import (
    NetworkError,
    SonarCheck,
    SonarCloudClient,
    _parse_issue,
    _parse_pr,
    check_sonar_status,
    summarize_checks,
)
from repo_tui.models import SonarStatus


def _config(tmp_path: Path, **overrides) -> Config:
    cfg = tmp_path / ".repo-overview.json"
    cfg.write_text(json.dumps({"local_code_path": str(tmp_path), **overrides}))
    return Config(str(cfg))


# ---------- summarize_checks ------------------------------------------------------


@pytest.mark.parametrize(
    ("rollup", "expected"),
    [
        # gh returns a dict for some queries and a bare list for others.
        ({"contexts": [{"conclusion": "SUCCESS"}]}, "SUCCESS"),
        ([{"state": "success"}], "SUCCESS"),
        # Failure wins over everything.
        ([{"state": "SUCCESS"}, {"state": "FAILURE"}], "FAILURE"),
        ([{"state": "PENDING"}, {"state": "FAILURE"}], "FAILURE"),
        ([{"state": "TIMED_OUT"}], "FAILURE"),
        # Pending wins over success.
        ([{"state": "SUCCESS"}, {"state": "IN_PROGRESS"}], "PENDING"),
        # Nothing to summarize.
        (None, None),
        ([], None),
        ({}, None),
        ({"contexts": None}, None),
        ("garbage", None),
        # A context with neither field reported.
        ([{}], None),
    ],
)
def test_summarize_checks(rollup: object, expected: str | None) -> None:
    assert summarize_checks(rollup) == expected


def test_summarize_checks_mixed_state_and_conclusion_keys() -> None:
    """Status checks report "state"; check runs report "conclusion"."""
    assert summarize_checks([{"state": "SUCCESS"}, {"conclusion": "success"}]) == "SUCCESS"


# ---------- _parse_pr / _parse_issue ----------------------------------------------


def test_parse_pr_full_payload() -> None:
    pr = _parse_pr(
        {
            "number": 7,
            "title": "Bump x",
            "url": "https://example.invalid/7",
            "author": {"login": "dependabot[bot]", "name": "Dependabot"},
            "state": "OPEN",
            "isDraft": True,
            "labels": [{"name": "deps"}],
            "body": "body",
            "reviewRequests": [{"login": "alice"}, {}],
            "reviewDecision": "APPROVED",
            "headRefName": "dependabot/x",
            "baseRefName": "main",
            "mergeable": "MERGEABLE",
            "statusCheckRollup": [{"state": "SUCCESS"}],
        }
    )

    assert pr.number == 7
    assert pr.author == "dependabot[bot]"
    assert pr.author_name == "Dependabot"
    assert pr.draft is True
    assert pr.labels == ["deps"]
    assert pr.reviewers == ["alice"]  # entries without a login are dropped
    assert pr.checks_status == "SUCCESS"


def test_parse_pr_minimal_payload() -> None:
    """gh omits keys rather than sending nulls when fields are unset."""
    pr = _parse_pr({"number": 1, "title": "t", "url": "u", "state": "OPEN"})

    assert pr.author == "unknown"
    assert pr.author_name is None
    assert pr.draft is False
    assert pr.labels == []
    assert pr.reviewers is None  # empty list becomes None, not []
    assert pr.checks_status is None


def test_parse_issue_assignee_and_body() -> None:
    issue = _parse_issue(
        {
            "number": 3,
            "title": "t",
            "url": "u",
            "labels": [{"name": "bug"}],
            "state": "OPEN",
            "body": None,  # gh sends null for an empty body
            "assignees": [{"login": "bob"}],
        }
    )

    assert issue.labels == ["bug"]
    assert issue.body == ""
    assert issue.assignee == "bob"


def test_parse_issue_without_assignees() -> None:
    issue = _parse_issue({"number": 1, "title": "t", "url": "u", "state": "OPEN"})
    assert issue.assignee is None
    assert issue.labels == []


# ---------- check_sonar_status ----------------------------------------------------


@pytest.mark.asyncio
async def test_sonar_check_stops_at_the_first_key_that_answers(tmp_path: Path) -> None:
    config = _config(tmp_path)
    sonar = SonarCloudClient(config)
    found = SonarStatus(project_key="k", status="OK", url="u", conditions=[])

    with patch.object(SonarCloudClient, "get_project_status", new_callable=AsyncMock) as get_status:
        get_status.side_effect = [None, found, None]
        result = await check_sonar_status(config, sonar, "adamkwhite", "repo-tui")

    assert result == SonarCheck(found, checked=True, unreachable=False)
    assert get_status.await_count == 2  # stopped as soon as one answered


@pytest.mark.asyncio
async def test_sonar_check_reports_unreachable_without_retrying(tmp_path: Path) -> None:
    """A dead instance means every remaining key spelling repeats the timeout."""
    config = _config(tmp_path)
    sonar = SonarCloudClient(config)

    with patch.object(SonarCloudClient, "get_project_status", new_callable=AsyncMock) as get_status:
        get_status.side_effect = NetworkError("timed out")
        result = await check_sonar_status(config, sonar, "adamkwhite", "repo-tui")

    assert result == SonarCheck(None, checked=True, unreachable=True)
    assert get_status.await_count == 1


@pytest.mark.asyncio
async def test_sonar_check_exhausting_keys_is_not_unreachable(tmp_path: Path) -> None:
    """No project found is a real answer, distinct from "could not ask"."""
    config = _config(tmp_path)
    sonar = SonarCloudClient(config)

    with patch.object(SonarCloudClient, "get_project_status", new_callable=AsyncMock) as get_status:
        get_status.return_value = None
        result = await check_sonar_status(config, sonar, "adamkwhite", "repo-tui")

    assert result.status is None
    assert result.checked is True
    assert result.unreachable is False
    assert get_status.await_count == len(sonar.guess_project_key("adamkwhite", "repo-tui"))
