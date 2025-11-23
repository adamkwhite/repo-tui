"""Configuration management for repo overview."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class Config:
    """Configuration management."""

    def __init__(self, config_path: str = "~/.repo-overview.json") -> None:
        self.config_path = Path(config_path).expanduser()
        self.data = self._load_config()

    def _load_config(self) -> dict[str, Any]:
        """Load configuration from file or create default."""
        if self.config_path.exists():
            with open(self.config_path) as f:
                return json.load(f)

        default_config: dict[str, Any] = {
            "excluded_repos": [],
            "sonarcloud_org": None,
            "github_org": None,
            "local_code_path": "~/Code",
        }
        self._save_config(default_config)
        return default_config

    def _save_config(self, config: dict[str, Any]) -> None:
        """Save configuration to file."""
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.config_path, "w") as f:
            json.dump(config, f, indent=2)

    def is_excluded(self, repo_name: str) -> bool:
        """Check if a repository is excluded."""
        return repo_name in self.data.get("excluded_repos", [])

    def get_sonarcloud_org(self) -> str | None:
        """Get SonarCloud organization name."""
        return self.data.get("sonarcloud_org")

    def get_local_code_path(self) -> Path:
        """Get the local code directory path."""
        return Path(self.data.get("local_code_path", "~/Code")).expanduser()
