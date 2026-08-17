"""The debug-log naming convention, enforced rather than documented.

The names drifted once: three writes went to `grid_debug.log`, which matched
neither the location nor the naming of the other four, and nothing caught it.
A closed enum plus these tests means a new log has to join the set, and a
member that breaks the convention fails CI.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from unittest.mock import patch

import pytest

from repo_tui import config as config_module
from repo_tui.config import LOG_NAME_RE, Config, DebugLog


@pytest.fixture
def log_dir(tmp_path: Path):
    target = tmp_path / "logs"
    with patch.object(config_module, "LOG_DIR", target):
        yield target


def _config(tmp_path: Path, debug: bool = True) -> Config:
    cfg = tmp_path / ".repo-overview.json"
    cfg.write_text(json.dumps({"debug": debug}))
    return Config(str(cfg))


# ---------- the convention --------------------------------------------------------


@pytest.mark.parametrize("member", list(DebugLog))
def test_every_name_follows_the_convention(member: DebugLog) -> None:
    """<subsystem>-<action>: lowercase, hyphen-separated, no extension."""
    assert LOG_NAME_RE.match(member.value), (
        f"{member.name} = {member.value!r} breaks the convention"
    )


@pytest.mark.parametrize(
    "bad",
    [
        "grid_debug",  # underscores — the exact drift this replaces
        "grid-debug.log",  # extension belongs to the writer, not the name
        "PR-Fetch",  # uppercase
        "prfetch",  # no subsystem/action split
        "pr--fetch",  # empty segment
        "-pr-fetch",  # leading separator
        "pr-fetch-",  # trailing separator
    ],
)
def test_convention_rejects_malformed_names(bad: str) -> None:
    assert not LOG_NAME_RE.match(bad)


def test_names_are_unique() -> None:
    values = [m.value for m in DebugLog]
    assert len(values) == len(set(values))


# ---------- enforcement at the writer ---------------------------------------------


def test_unknown_name_is_rejected(tmp_path: Path, log_dir: Path) -> None:
    """Adding a log means adding an enum member, not inventing a filename."""
    with pytest.raises(ValueError):
        _config(tmp_path).debug_log("grid_debug", "hello\n")

    assert not log_dir.exists()


@pytest.mark.usefixtures("log_dir")
def test_unknown_name_is_rejected_even_when_debug_is_off(tmp_path: Path) -> None:
    """The typo is a bug whether or not logging happens to be on."""
    with pytest.raises(ValueError):
        _config(tmp_path, debug=False).debug_log("nope", "hello\n")


def test_plain_string_matching_a_member_is_accepted(tmp_path: Path, log_dir: Path) -> None:
    _config(tmp_path).debug_log("pr-fetch", "hello\n")

    assert (log_dir / "pr-fetch.log").read_text() == "hello\n"


@pytest.mark.parametrize("member", list(DebugLog))
def test_each_member_writes_its_own_file(tmp_path: Path, log_dir: Path, member: DebugLog) -> None:
    _config(tmp_path).debug_log(member, "x\n")

    assert [p.name for p in log_dir.iterdir()] == [f"{member.value}.log"]


def test_enum_is_the_full_set_of_logs_written() -> None:
    """Guards against a log being added to the enum but never wired up, and
    against source writing a log filename that bypasses debug_log entirely."""
    src = Path(__file__).resolve().parent.parent / "src" / "repo_tui"
    sources = "\n".join(p.read_text() for p in src.rglob("*.py"))

    for member in DebugLog:
        constant = f"DebugLog.{member.name}"
        assert constant in sources, f"{constant} is declared but never used"

    # config.py holds the only open() of a log file; every other module has to
    # go through debug_log, so a new log cannot skip the naming rule.
    # A log *filename* is a string literal ending in .log — distinct from
    # `self.log(...)` (Textual's logger) or `self.log_lines` (the merge modal).
    filename_literal = re.compile(r"""\.log['"]""")
    for path in src.rglob("*.py"):
        if path.name == "config.py":
            continue
        assert not filename_literal.search(path.read_text()), (
            f"{path.name} names a log file directly instead of using debug_log"
        )
