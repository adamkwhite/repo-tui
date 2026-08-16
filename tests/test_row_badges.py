"""The badge builders extracted from the list row and the grid card.

They were branches inside two 40-line render functions, which meant the only
way to assert "a repo we could not read never renders green" was to build a
widget and scrape markup out of it. As plain functions the priority order is
directly assertable.
"""

from __future__ import annotations

import pytest

from repo_tui.models import Issue, PullRequest, RepoOverview, SonarStatus
from repo_tui.widgets.repo_grid import (
    card_activity,
    card_counts,
    card_git_status,
    card_sonar,
    card_tags,
)
from repo_tui.widgets.repo_list import counts_badge, local_badge, sonar_badge, status_icon


def _repo(**kwargs) -> RepoOverview:
    defaults = {
        "name": "widget-api",
        "owner": "adamkwhite",
        "url": "https://github.com/adamkwhite/widget-api",
        "open_issues_count": 0,
        "issues": [],
        "sonar_status": None,
    }
    return RepoOverview(**{**defaults, **kwargs})


def _bug(number: int = 1) -> Issue:
    return Issue(number=number, title="t", url="u", labels=["bug"], state="OPEN")


def _pr(number: int = 1) -> PullRequest:
    return PullRequest(number=number, title="t", url="u", author="a", state="OPEN")


def _sonar(status: str, conditions: list[dict[str, str]] | None = None) -> SonarStatus:
    return SonarStatus(project_key="k", status=status, url="u", conditions=conditions or [])


# ---------- status_icon: priority order ------------------------------------------


@pytest.mark.parametrize(
    ("repo", "expected"),
    [
        (_repo(fetch_failed=True), "magenta"),
        (_repo(local_path="/x", has_uncommitted_changes=None), "magenta"),
        (_repo(sonar_status=_sonar("ERROR")), "red"),
        (_repo(issues=[_bug(i) for i in range(5)]), "red"),
        (_repo(sonar_status=_sonar("WARN")), "yellow"),
        (_repo(local_path="/x", has_uncommitted_changes=True), "yellow"),
        (_repo(issues=[_bug()]), "yellow"),
        (_repo(pull_requests=[_pr()]), "blue"),
        (_repo(), "green"),
    ],
)
def test_status_icon_colors(repo: RepoOverview, expected: str) -> None:
    assert expected in status_icon(repo)


def test_unknown_outranks_every_healthy_signal() -> None:
    """A repo we could not read must never win the green dot on a technicality."""
    unread = _repo(fetch_failed=True, pull_requests=[], issues=[], sonar_status=_sonar("OK"))

    assert "green" not in status_icon(unread)
    assert "magenta" in status_icon(unread)


def test_sonar_error_outranks_a_single_critical_issue() -> None:
    repo = _repo(sonar_status=_sonar("ERROR"), issues=[_bug()])
    assert "red" in status_icon(repo)


# ---------- counts ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("repo", "expected"),
    [
        (_repo(), ""),
        (_repo(open_issues_count=1), "1 issue"),
        (_repo(open_issues_count=3), "3 issues"),
        (_repo(pull_requests=[_pr()]), "1 PR"),
        (_repo(pull_requests=[_pr(1), _pr(2)]), "2 PRs"),
    ],
)
def test_counts_badge_pluralization(repo: RepoOverview, expected: str) -> None:
    assert expected in counts_badge(repo)


def test_counts_badge_reports_failure_over_zero() -> None:
    repo = _repo(fetch_failed=True, open_issues_count=0)
    assert "fetch failed" in counts_badge(repo)


# ---------- local / git state -----------------------------------------------------


@pytest.mark.parametrize(
    ("repo", "expected"),
    [
        (_repo(), "remote"),
        (_repo(local_path="/x", has_uncommitted_changes=None), "git status unknown"),
        (_repo(local_path="/x", has_uncommitted_changes=True, current_branch="fix/a"), "fix/a"),
        (_repo(local_path="/x", has_uncommitted_changes=True), "uncommitted"),
        (_repo(local_path="/x", current_branch="main"), "main"),
        (_repo(local_path="/x"), ""),
    ],
)
def test_local_badge(repo: RepoOverview, expected: str) -> None:
    assert expected in local_badge(repo)


def test_unknown_git_state_is_not_reported_as_clean() -> None:
    unknown = _repo(local_path="/x", has_uncommitted_changes=None)
    clean = _repo(local_path="/x", current_branch="main")

    assert local_badge(unknown) != local_badge(clean)
    assert "unknown" in local_badge(unknown)


# ---------- sonar -----------------------------------------------------------------


def test_sonar_badge_names_the_failing_metrics() -> None:
    repo = _repo(
        sonar_status=_sonar(
            "ERROR",
            [
                {"metricKey": "new_coverage", "status": "ERROR"},
                {"metricKey": "new_bugs", "status": "OK"},
            ],
        )
    )
    badge = sonar_badge(repo)

    assert "new_coverage" in badge
    assert "new_bugs" not in badge  # passing conditions are not failures


def test_sonar_badge_caps_the_metric_list() -> None:
    conditions = [{"metricKey": f"m{i}", "status": "ERROR"} for i in range(6)]
    badge = sonar_badge(_repo(sonar_status=_sonar("ERROR", conditions)))

    assert badge.count(",") == 2  # three metrics, so two separators


def test_unreachable_is_not_no_project() -> None:
    unreachable = sonar_badge(_repo(sonar_unreachable=True, sonar_checked=True))
    absent = sonar_badge(_repo(sonar_checked=True))

    assert "unreachable" in unreachable
    assert "No Sonar" in absent
    assert unreachable != absent


def test_sonar_badge_empty_when_never_checked() -> None:
    assert sonar_badge(_repo()) == ""


@pytest.mark.parametrize(
    ("status", "expected"),
    [("WARN", "⚠ Quality Gate"), ("OK", "✓ Sonar"), ("NONE", "")],
)
def test_sonar_badge_non_error_states(status: str, expected: str) -> None:
    badge = sonar_badge(_repo(sonar_status=_sonar(status)))
    assert expected in badge if expected else badge == ""


# ---------- grid card -------------------------------------------------------------


def test_card_counts_matches_list_semantics() -> None:
    assert "fetch failed" in card_counts(_repo(fetch_failed=True))
    assert "No issues or PRs" in card_counts(_repo())
    # The card colors the number separately, so the count and its label are
    # split by markup: "[cyan]1[/cyan] issue".
    assert card_counts(_repo(open_issues_count=1)).endswith(" issue")
    assert card_counts(_repo(open_issues_count=2)).endswith(" issues")


@pytest.mark.parametrize(
    ("repo", "expected"),
    [
        (_repo(), "remote"),
        (_repo(local_path="/x", has_uncommitted_changes=None), "git status unknown"),
        (_repo(local_path="/x", has_uncommitted_changes=True), "local"),
        (_repo(local_path="/x", current_branch="main"), "main"),
        (_repo(local_path="/x"), "local"),
    ],
)
def test_card_git_status(repo: RepoOverview, expected: str) -> None:
    assert expected in card_git_status(repo)


def test_card_tags_joins_only_what_exists() -> None:
    assert card_tags(_repo()) == ""
    assert card_tags(_repo(language="Python")) == "[cyan]Python[/cyan]"
    assert " · " in card_tags(_repo(language="Python", topics=["aws"]))


@pytest.mark.parametrize(
    ("repo", "expected"),
    [
        (_repo(), "🟢"),
        (_repo(open_issues_count=2), "🟡"),
        (_repo(open_issues_count=5), "🔥"),
        (_repo(open_issues_count=1), ""),
        (_repo(fetch_failed=True), ""),
        (_repo(local_path="/x", has_uncommitted_changes=None), ""),
    ],
)
def test_card_activity(repo: RepoOverview, expected: str) -> None:
    assert card_activity(repo) == expected


def test_card_sonar_unknown_status_renders_nothing() -> None:
    assert card_sonar(_repo(sonar_status=_sonar("NONE"))) == ""
    assert "unreachable" in card_sonar(_repo(sonar_unreachable=True))
