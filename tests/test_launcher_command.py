"""Tests for the wt.exe command construction and launch_claude error paths.

build_wt_command hands a string to bash -c, so quoting bugs here are how a
repo name or issue title turns into arbitrary shell. launch_claude is the only
place the TUI spawns a process, and every failure has to come back as a status
string rather than an exception that would tear down the app.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import mock_open, patch

import pytest

from repo_tui.config import Config
from repo_tui.launcher import (
    build_wt_command,
    check_repo_local,
    launch_claude,
    reset_terminal_modes,
)
from repo_tui.models import Issue, PullRequest, RepoOverview


def _config(tmp_path: Path, **overrides) -> Config:
    cfg_path = tmp_path / ".repo-overview.json"
    cfg_path.write_text(json.dumps({"local_code_path": str(tmp_path), **overrides}))
    return Config(str(cfg_path))


def _repo(local_path: str | None = "/home/adam/Code/widget-api") -> RepoOverview:
    return RepoOverview(
        name="widget-api",
        owner="adamkwhite",
        url="https://github.com/adamkwhite/widget-api",
        open_issues_count=0,
        issues=[],
        sonar_status=None,
        local_path=local_path,
    )


# ---------- build_wt_command -----------------------------------------------------


def test_wt_command_shape() -> None:
    cmd = build_wt_command(_repo(), "claude")

    assert cmd[0] == "wt.exe"
    assert "--suppressApplicationTitle" in cmd
    # Tab title is the repo name, and -d is followed by the working directory.
    assert cmd[cmd.index("--title") + 1] == "widget-api"
    assert cmd[cmd.index("-d") + 1].startswith("\\\\wsl$\\Ubuntu\\home")
    # Everything after `bash -i -c` is a single string for the shell.
    assert cmd[-2] == "-c"
    assert cmd[-1].startswith("reset && claude ")


def test_wt_command_uses_configured_claude_path() -> None:
    cmd = build_wt_command(_repo(), "/home/adam/.claude/local/claude")
    assert cmd[-1].startswith("reset && /home/adam/.claude/local/claude ")


def test_wt_command_escapes_single_quotes_in_title() -> None:
    """A title with an apostrophe must not break out of the single-quoted arg."""
    issue = Issue(
        number=9,
        title="Fix Bob's broken '; rm -rf /' handling",
        url="u",
        labels=[],
        state="OPEN",
    )
    payload = build_wt_command(_repo(), "claude", issue=issue)[-1]

    # bash's own escape for a quote inside a single-quoted string.
    assert "'\\''" in payload
    # No bare apostrophe survives to terminate the quoted section early.
    assert "Bob's" not in payload


def test_wt_command_remote_repo_has_empty_working_dir() -> None:
    cmd = build_wt_command(_repo(local_path=None), "claude")
    assert cmd[cmd.index("-d") + 1] == ""


def test_wt_command_pr_takes_precedence_over_issue() -> None:
    issue = Issue(number=1, title="issue title", url="u", labels=[], state="OPEN")
    pr = PullRequest(number=2, title="pr title", url="u", author="a", state="OPEN")

    payload = build_wt_command(_repo(), "claude", issue=issue, pr=pr)[-1]

    assert "PR #2" in payload
    assert "issue title" not in payload


# ---------- launch_claude --------------------------------------------------------


def test_launch_refuses_repo_with_no_checkout(tmp_path: Path) -> None:
    with patch("subprocess.Popen") as popen:
        msg = launch_claude(_repo(local_path=None), _config(tmp_path))

    assert "not found locally" in msg
    popen.assert_not_called()


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({}, "Launched Claude for widget-api"),
        (
            {"issue": Issue(number=42, title="t", url="u", labels=[], state="OPEN")},
            "Launched Claude for widget-api #42",
        ),
        (
            {"pr": PullRequest(number=7, title="t", url="u", author="a", state="OPEN")},
            "Launched Claude for widget-api PR #7",
        ),
    ],
)
def test_launch_reports_what_it_started(tmp_path: Path, kwargs: dict, expected: str) -> None:
    with patch("subprocess.Popen") as popen:
        msg = launch_claude(_repo(), _config(tmp_path), **kwargs)

    assert msg == expected
    popen.assert_called_once()
    # Detached, so quitting the TUI doesn't kill the Claude tab.
    assert popen.call_args.kwargs["start_new_session"] is True


def test_launch_returns_message_when_wt_missing(tmp_path: Path) -> None:
    """No wt.exe (plain Linux, not WSL) must not raise into the TUI."""
    err = FileNotFoundError(2, "No such file or directory")
    err.filename = "wt.exe"

    with patch("subprocess.Popen", side_effect=err):
        msg = launch_claude(_repo(), _config(tmp_path))

    assert msg == "Error: File not found - wt.exe"


def test_launch_returns_message_on_unexpected_error(tmp_path: Path) -> None:
    with patch("subprocess.Popen", side_effect=PermissionError("denied")):
        msg = launch_claude(_repo(), _config(tmp_path))

    assert msg.startswith("Error launching: ")


def test_launch_writes_no_debug_log_by_default(tmp_path: Path) -> None:
    config = _config(tmp_path)  # built first: Config itself reads a file

    with patch("subprocess.Popen"), patch("builtins.open") as fake_open:
        launch_claude(_repo(), config)

    fake_open.assert_not_called()


def test_launch_writes_debug_log_when_enabled(tmp_path: Path) -> None:
    config = _config(tmp_path, debug=True)

    with patch("subprocess.Popen"), patch("builtins.open", mock_open()) as fake_open:
        launch_claude(_repo(), config)

    fake_open.assert_called()
    written = "".join(call.args[0] for call in fake_open().write.call_args_list)
    assert "widget-api" in written


def test_launch_logs_the_failure_when_debug_enabled(tmp_path: Path) -> None:
    config = _config(tmp_path, debug=True)

    with (
        patch("subprocess.Popen", side_effect=PermissionError("denied")),
        patch("builtins.open", mock_open()) as fake_open,
    ):
        msg = launch_claude(_repo(), config)

    written = "".join(call.args[0] for call in fake_open().write.call_args_list)
    assert "denied" in written
    assert msg.startswith("Error launching: ")


def test_launch_masks_private_repo_name_in_status(tmp_path: Path) -> None:
    """Privacy mode is for screen-shares; the status bar must not leak the name."""
    repo = _repo()
    repo.is_private = True
    RepoOverview.privacy_mode = True
    try:
        with patch("subprocess.Popen"):
            msg = launch_claude(repo, _config(tmp_path))
    finally:
        RepoOverview.privacy_mode = False

    assert "widget-api" not in msg
    assert "wi******-api"[:2] in msg


# ---------- misc -----------------------------------------------------------------


def test_check_repo_local(tmp_path: Path) -> None:
    (tmp_path / "widget-api").mkdir()
    (tmp_path / "not-a-dir").write_text("")

    assert check_repo_local("widget-api", str(tmp_path)) == str(tmp_path / "widget-api")
    assert check_repo_local("missing", str(tmp_path)) is None
    assert check_repo_local("not-a-dir", str(tmp_path)) is None


def test_reset_terminal_modes_disables_mouse_tracking(capsys) -> None:
    reset_terminal_modes()

    out = capsys.readouterr().out
    for code in ("\x1b[?1000l", "\x1b[?1002l", "\x1b[?1003l", "\x1b[?1006l"):
        assert code in out
