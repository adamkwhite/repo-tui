"""Debug logs are opt-in and live under the user's cache dir, not the temp dir.

A fixed path in a world-writable directory is pre-creatable and symlink-able by
any other user on the box (Sonar python:S5443), and it evaporates on reboot
exactly when yesterday's log would have been useful.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from repo_tui import config as config_module
from repo_tui.config import Config


@pytest.fixture
def log_dir(tmp_path: Path):
    """Point LOG_DIR at a temp dir so tests never touch the real cache."""
    target = tmp_path / "logs"
    with patch.object(config_module, "LOG_DIR", target):
        yield target


def _config(tmp_path: Path, debug: bool) -> Config:
    cfg_path = tmp_path / ".repo-overview.json"
    cfg_path.write_text(json.dumps({"debug": debug}))
    return Config(str(cfg_path))


def test_no_file_written_when_debug_disabled(tmp_path: Path, log_dir: Path) -> None:
    _config(tmp_path, debug=False).debug_log("sonar-fetch", "hello\n")

    assert not log_dir.exists()


def test_writes_under_cache_dir_when_enabled(tmp_path: Path, log_dir: Path) -> None:
    _config(tmp_path, debug=True).debug_log("sonar-fetch", "hello\n")

    assert (log_dir / "sonar-fetch.log").read_text() == "hello\n"


def test_appends_rather_than_truncating(tmp_path: Path, log_dir: Path) -> None:
    config = _config(tmp_path, debug=True)
    config.debug_log("pr-fetch", "first\n")
    config.debug_log("pr-fetch", "second\n")

    assert (log_dir / "pr-fetch.log").read_text() == "first\nsecond\n"


def test_separate_names_get_separate_files(tmp_path: Path, log_dir: Path) -> None:
    config = _config(tmp_path, debug=True)
    config.debug_log("pr-fetch", "a\n")
    config.debug_log("claude-launch", "b\n")

    assert sorted(p.name for p in log_dir.iterdir()) == ["claude-launch.log", "pr-fetch.log"]


@pytest.mark.usefixtures("log_dir")
def test_unwritable_log_dir_does_not_raise(tmp_path: Path) -> None:
    """Diagnostics must never take down the app they are diagnosing."""
    config = _config(tmp_path, debug=True)

    with patch("pathlib.Path.mkdir", side_effect=PermissionError("read-only fs")):
        config.debug_log("pr-fetch", "hello\n")  # must not raise


def test_default_log_dir_is_under_user_cache() -> None:
    assert Path("~/.cache/repo-tui/logs").expanduser() == config_module.LOG_DIR
    assert "/tmp" not in str(config_module.LOG_DIR)
