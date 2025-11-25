"""Configuration management for repo overview."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False


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
                if self.config_path.suffix in ['.yaml', '.yml']:
                    if not HAS_YAML:
                        raise ImportError("pyyaml is required for YAML config. Install with: pip install pyyaml")
                    return yaml.safe_load(f) or {}
                else:
                    return json.load(f)

        default_config: dict[str, Any] = {
            "included_repos": [],  # If set, ONLY show these repos (whitelist)
            "excluded_repos": [],  # If included_repos is empty, hide these repos (blacklist)
            "sonarcloud_org": None,
            "github_org": None,
            "local_code_path": "~/Code",
            "sonar_url": None,  # Self-hosted SonarQube URL (e.g., https://sonar.company.com)
            "sonar_token": None,  # SonarQube authentication token (direct)
            "sonar_token_pass": None,  # SonarQube token from pass (e.g., "work/sonarqube")
        }
        self._save_config(default_config)
        return default_config

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
        token = self.data.get("sonar_token")
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
