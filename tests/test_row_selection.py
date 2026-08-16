"""Resolving the highlighted row back to the repo, issue, or PR it stands for.

Every action key (`o`, `c`, `e`) routes through these, and an expanded repo
interleaves child rows with repo rows, so "which thing is under the cursor"
is the question the whole keymap depends on.
"""

from __future__ import annotations

import pytest

from repo_tui.app import RepoOverviewApp
from repo_tui.models import Issue, PullRequest, RepoOverview
from repo_tui.widgets.repo_list import RepoListWidget


def _repo(name: str = "widget-api", *, issues=None, prs=None) -> RepoOverview:
    return RepoOverview(
        name=name,
        owner="adamkwhite",
        url=f"https://github.com/adamkwhite/{name}",
        open_issues_count=len(issues or []),
        issues=issues or [],
        sonar_status=None,
        pull_requests=prs or [],
    )


def _issue(number: int) -> Issue:
    return Issue(number=number, title=f"issue {number}", url="u", labels=[], state="OPEN")


def _pr(number: int) -> PullRequest:
    return PullRequest(number=number, title=f"pr {number}", url="u", author="a", state="OPEN")


async def _widget_with(repos: list[RepoOverview], expanded: set[str] | None = None):
    """Mount the app and return (pilot ctx, widget) with repos loaded."""
    app = RepoOverviewApp()
    ctx = app.run_test()
    pilot = await ctx.__aenter__()
    await pilot.pause()
    widget = app.query_one("#repo-list", RepoListWidget)
    if expanded:
        widget.expanded = set(expanded)
    widget.set_repos(repos)
    await pilot.pause()
    return ctx, widget


def _index_of(widget: RepoListWidget, option_id: str) -> int:
    for i in range(widget.option_count):
        option = widget.get_option_at_index(i)
        if option and option.id == option_id:
            return i
    raise AssertionError(f"no row with id {option_id}")


@pytest.mark.asyncio
async def test_child_rows_resolve_to_their_issue_and_pr() -> None:
    repo = _repo(issues=[_issue(1), _issue(2)], prs=[_pr(7)])
    ctx, widget = await _widget_with([repo], expanded={"widget-api"})
    try:
        widget.highlighted = _index_of(widget, "issue:widget-api:2")
        match = widget.get_selected_inline_issue()
        assert match is not None
        assert match[0].name == "widget-api"
        assert match[1].number == 2
        # An issue row is not a PR row.
        assert widget.get_selected_inline_pr() is None

        widget.highlighted = _index_of(widget, "pr:widget-api:7")
        pr_match = widget.get_selected_inline_pr()
        assert pr_match is not None
        assert pr_match[1].number == 7
        assert widget.get_selected_inline_issue() is None
    finally:
        await ctx.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_child_row_still_resolves_to_its_parent_repo() -> None:
    """`o` on an issue row must know which repo the issue belongs to."""
    repo = _repo(issues=[_issue(1)])
    ctx, widget = await _widget_with([repo], expanded={"widget-api"})
    try:
        widget.highlighted = _index_of(widget, "issue:widget-api:1")
        selected = widget.get_selected_repo()
        assert selected is not None
        assert selected.name == "widget-api"
    finally:
        await ctx.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_repo_row_is_not_an_inline_child() -> None:
    repo = _repo(issues=[_issue(1)], prs=[_pr(1)])
    ctx, widget = await _widget_with([repo], expanded={"widget-api"})
    try:
        widget.highlighted = _index_of(widget, "repo:widget-api")
        assert widget.get_selected_inline_issue() is None
        assert widget.get_selected_inline_pr() is None
        assert widget.get_selected_repo() is not None
    finally:
        await ctx.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_action_row_resolves_to_nothing() -> None:
    ctx, widget = await _widget_with([_repo()])
    try:
        widget.highlighted = 0  # the Dependabot pseudo-row
        assert widget.get_selected_repo() is None
        assert widget.get_selected_inline_issue() is None
        assert widget.get_selected_inline_pr() is None
    finally:
        await ctx.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_nothing_highlighted_resolves_to_nothing() -> None:
    ctx, widget = await _widget_with([_repo()])
    try:
        widget.highlighted = None
        assert widget.get_selected_repo() is None
        assert widget.get_selected_inline_issue() is None
        assert widget.get_selected_inline_pr() is None
    finally:
        await ctx.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_expanded_rows_are_description_then_prs_then_issues() -> None:
    repo = _repo(issues=[_issue(1)], prs=[_pr(9)])
    ctx, widget = await _widget_with([repo], expanded={"widget-api"})
    try:
        ids = [
            widget.get_option_at_index(i).id  # type: ignore[union-attr]
            for i in range(widget.option_count)
        ]
        assert ids[1] == "repo:widget-api"
        assert ids[3] == "pr:widget-api:9"
        assert ids[4] == "issue:widget-api:1"
    finally:
        await ctx.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_collapsed_repo_shows_no_child_rows() -> None:
    repo = _repo(issues=[_issue(1)], prs=[_pr(9)])
    ctx, widget = await _widget_with([repo])
    try:
        ids = [
            widget.get_option_at_index(i).id  # type: ignore[union-attr]
            for i in range(widget.option_count)
        ]
        assert ids == ["action:dependabot-merge", "repo:widget-api"]
    finally:
        await ctx.__aexit__(None, None, None)
