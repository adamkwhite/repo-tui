"""Configuration management for repo overview."""

from __future__ import annotations

import json
import re
from enum import StrEnum
from pathlib import Path
from typing import Any

try:
    import yaml

    HAS_YAML = True
except ImportError:
    HAS_YAML = False


# Debug logs live beside the repo cache, not in the shared world-writable
# temp dir: anyone on the box can pre-create or symlink a fixed name there
# (Sonar python:S5443), and the files vanish on reboot exactly when you want
# yesterday's log.
LOG_DIR = Path("~/.cache/repo-tui/logs").expanduser()

# Every debug log the app writes. A closed set rather than a free-form string
# because the names drifted once already: three writes went to a
# `grid_debug.log` that matched neither the location nor the naming of the
# rest, and nothing flagged it.
#
# Convention: <subsystem>-<action>, lowercase, hyphen-separated, no extension
# (`.log` is appended when the file is opened). Enforced by LOG_NAME_RE below,
# which is asserted over this enum in the test suite — so a member that breaks
# the convention fails CI rather than silently creating an odd file.
LOG_NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)+$")


class DebugLog(StrEnum):
    """Names of the debug logs, one per subsystem that writes one."""

    PR_FETCH = "pr-fetch"
    SONAR_CHECK = "sonar-check"
    SONAR_FETCH = "sonar-fetch"
    CLAUDE_LAUNCH = "claude-launch"


class Config:
    """Configuration management."""

    def __init__(self, config_path: str | None = None) -> None:
        # Check for YAML config first (if pyyaml installed), then JSON
        if config_path:
            self.config_path = Path(config_path).expanduser()
        elif HAS_YAML and Path("~/.repo-overview.yaml").expanduser().exists():
            self.config_path = Path("~/.repo-overview.yaml").expanduser()
        else:
            self.config_path = Path("~/.repo-overview.json").expanduser()

        self.data = self._load_config()

    def _load_config(self) -> dict[str, Any]:
        """Load configuration from YAML or JSON file or create default."""
        if self.config_path.exists():
            with open(self.config_path) as f:
                if self.config_path.suffix in [".yaml", ".yml"]:
                    if not HAS_YAML:
                        raise ImportError(
                            "pyyaml is required for YAML config. Install with: pip install pyyaml"
                        )
                    data: dict[str, Any] = yaml.safe_load(f) or {}
                    return data
                else:
                    data_json: dict[str, Any] = json.load(f)
                    return data_json

        default_config: dict[str, Any] = {
            "included_repos": [],  # If set, ONLY show these repos (whitelist)
            "excluded_repos": [],  # If included_repos is empty, hide these repos (blacklist)
            "sonarcloud_org": None,
            "github_org": None,
            "local_code_path": "~/Code",
            "sonar_url": None,  # Self-hosted SonarQube URL (e.g., https://sonar.company.com)
            "sonar_token": None,  # SonarQube authentication token (direct)
            "sonar_token_pass": None,  # SonarQube token from pass (e.g., "work/sonarqube")
            "claude_command": "claude",  # Claude CLI command (e.g., "claude" or full path)
            "debug": False,  # Enable debug logging (sonar, claude launcher, etc.)
            "friendly_names": {},  # Map repo names to friendly display names
        }
        self._save_config(default_config)
        return default_config

    def debug_log(self, name: DebugLog | str, message: str) -> None:
        """Append to ~/.cache/repo-tui/logs/<name>.log when debug is enabled.

        Single entry point for every debug log in the app, so the location, the
        naming, and the "is debug on?" check live in one place instead of being
        re-derived at each call site — which is how the PR-fetch log ended up
        writing unconditionally, and how grid_debug.log ended up in the temp
        dir under a different naming scheme entirely.

        `name` must be a DebugLog member. A plain string is accepted for
        convenience and coerced, which raises ValueError for anything not in
        the enum: adding a log means adding a member, not inventing a filename
        at the call site. mypy catches it first; this catches the untyped path.
        """
        log_name = DebugLog(name)

        if not self.data.get("debug", False):
            return
        try:
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            with open(LOG_DIR / f"{log_name.value}.log", "a") as f:
                f.write(message)
        except OSError:
            # Diagnostics must never take down the app they are diagnosing.
            pass

    def _save_config(self, config: dict[str, Any]) -> None:
        """Save configuration to file."""
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.config_path, "w") as f:
            json.dump(config, f, indent=2)

    def should_include_repo(self, repo_name: str) -> bool:
        """Check if a repository should be included.

        Logic:
        - If included_repos is set (non-empty), ONLY show repos in that list
        - If included_repos is empty, show all repos EXCEPT those in excluded_repos
        """
        included_repos = self.data.get("included_repos", [])

        # Whitelist mode: if included_repos is set, only show those
        if included_repos:
            return repo_name in included_repos

        # Blacklist mode: show all except excluded
        excluded_repos = self.data.get("excluded_repos", [])
        return repo_name not in excluded_repos

    def is_excluded(self, repo_name: str) -> bool:
        """Check if a repository is excluded (legacy method, use should_include_repo instead)."""
        return not self.should_include_repo(repo_name)

    def get_sonarcloud_org(self) -> str | None:
        """Get SonarCloud organization name."""
        return self.data.get("sonarcloud_org")

    def get_local_code_path(self) -> Path:
        """Get the local code directory path."""
        return Path(self.data.get("local_code_path", "~/Code")).expanduser()

    def get_sonar_token(self) -> str | None:
        """Get SonarQube token from config or pass."""
        # Try direct token first
        token: str | None = self.data.get("sonar_token")
        if token:
            return token

        # Try fetching from pass
        pass_path = self.data.get("sonar_token_pass")
        if pass_path:
            try:
                import subprocess

                result = subprocess.run(
                    ["pass", pass_path],
                    capture_output=True,
                    text=True,
                    check=True,
                )
                return result.stdout.strip()
            except (subprocess.CalledProcessError, FileNotFoundError):
                return None

        return None

    def get_friendly_name(self, repo_name: str) -> str | None:
        """Get the friendly name for a repository, or None if not configured."""
        friendly_names: dict[str, str] = self.data.get("friendly_names", {})
        return friendly_names.get(repo_name)
