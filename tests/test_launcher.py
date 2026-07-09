"""Tests for the Claude Code launcher prompt building."""

from __future__ import annotations

from repo_tui.launcher import build_claude_prompt
from repo_tui.models import Issue, PullRequest


def test_default_prompt_uses_current_session_skill():
    # No issue/PR selected -> launch the start-of-session skill.
    # Pinned so a skill rename doesn't silently ship a dead slash-command again.
    assert build_claude_prompt() == "/StartSession"


def test_issue_prompt():
    issue = Issue(
        number=42,
        title="Fix the thing",
        url="u",
        labels=[],
        state="OPEN",
        body="",
        assignee=None,
    )
    assert build_claude_prompt(issue=issue) == "Work on issue #42: Fix the thing"


def test_pr_prompt_marks_draft():
    pr = PullRequest(
        number=7,
        title="Add feature",
        url="u",
        author="x",
        state="OPEN",
        draft=True,
        labels=[],
        body="",
        head_ref="h",
        base_ref="main",
    )
    assert build_claude_prompt(pr=pr) == "Work on PR #7 (DRAFT): Add feature"
