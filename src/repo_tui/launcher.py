"""Windows Terminal + Claude Code launcher."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from .models import Issue, PullRequest, RepoOverview


def reset_terminal_modes() -> None:
    """Reset terminal modes that might leak to child processes."""
    sys.stdout.write("\x1b[?1000l")  # Disable mouse click tracking
    sys.stdout.write("\x1b[?1002l")  # Disable mouse drag tracking
    sys.stdout.write("\x1b[?1003l")  # Disable all mouse tracking
    sys.stdout.write("\x1b[?1006l")  # Disable SGR mouse mode
    sys.stdout.flush()


def build_claude_prompt(issue: Issue | None = None, pr: PullRequest | None = None) -> str:
    """Build the prompt string for Claude Code."""
    if pr:
        draft_status = " (DRAFT)" if pr.draft else ""
        return f"Work on PR #{pr.number}{draft_status}: {pr.title}"
    if issue:
        return f"Work on issue #{issue.number}: {issue.title}"
    return "/StartOfTheDay"


def build_wt_command(repo: RepoOverview, issue: Issue | None = None, pr: PullRequest | None = None) -> list[str]:
    r"""Build Windows Terminal command to launch Claude Code.

    Command structure:
    wt.exe -w 0 nt --title "repo-name" --suppressApplicationTitle \
      -d "\\wsl$\Ubuntu\path\to\repo" \
      wsl.exe -d Ubuntu -- bash -c "reset && claude prompt"
    """
    prompt = build_claude_prompt(issue, pr)

    # WSL path for Windows Terminal (e.g., \\wsl$\Ubuntu\home\adam\Code\repo)
    wsl_path = repo.local_path.replace("/home/", r"\\wsl$\Ubuntu\home\\") if repo.local_path else ""

    # Escape single quotes in prompt for bash
    escaped_prompt = prompt.replace("'", "'\\''")

    # Build command - use full path to claude since PATH may not be set
    # Wrap in bash -c with 'reset' to clear any inherited terminal state
    return [
        "wt.exe",
        "-w",
        "0",
        "nt",
        "--title",
        repo.name,
        "--suppressApplicationTitle",
        "-d",
        wsl_path,
        "wsl.exe",
        "-d",
        "Ubuntu",
        "--",
        "bash",
        "-c",
        f"reset && /home/adam/.claude/local/claude '{escaped_prompt}'",
    ]


def launch_claude(repo: RepoOverview, issue: Issue | None = None, pr: PullRequest | None = None) -> str:
    """Launch Claude Code in a new Windows Terminal tab.

    Returns a status message.
    """
    if not repo.local_path:
        return f"Repo not found locally: ~/Code/{repo.name}"

    try:
        cmd = build_wt_command(repo, issue, pr)

        subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

        if pr:
            return f"Launched Claude for {repo.name} PR #{pr.number}"
        if issue:
            return f"Launched Claude for {repo.name} #{issue.number}"
        return f"Launched Claude for {repo.name}"

    except FileNotFoundError:
        return "Error: wt.exe not found. Is Windows Terminal installed?"
    except Exception as e:
        return f"Error launching: {e}"


def check_repo_local(repo_name: str, base_path: str = "/home/adam/Code") -> str | None:
    """Check if a repository exists locally.

    Returns the full path if it exists, None otherwise.
    """
    repo_path = Path(base_path) / repo_name
    if repo_path.exists() and repo_path.is_dir():
        return str(repo_path)
    return None
