"""Windows Terminal + Claude Code launcher."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from .models import Issue, PullRequest, RepoOverview

if TYPE_CHECKING:
    from .config import Config


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


def build_wt_command(
    repo: RepoOverview,
    claude_command: str,
    issue: Issue | None = None,
    pr: PullRequest | None = None,
) -> list[str]:
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

    # Build command - use configured claude command
    # Use bash -i (interactive) to ensure .bashrc is loaded (bypasses non-interactive guard)
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
        "-i",
        "-c",
        f"reset && {claude_command} '{escaped_prompt}'",
    ]


def launch_claude(
    repo: RepoOverview,
    config: Config,
    issue: Issue | None = None,
    pr: PullRequest | None = None,
) -> str:
    """Launch Claude Code in a new Windows Terminal tab.

    Returns a status message.
    """
    if not repo.local_path:
        return f"Repo not found locally: ~/Code/{repo.name}"

    try:
        # Get claude command from config, default to "claude"
        claude_command = config.data.get("claude_command", "claude")
        cmd = build_wt_command(repo, claude_command, issue, pr)

        # Debug logging (if enabled)
        if config.data.get("debug", False):  # Reuse debug flag
            with open("/tmp/claude-launch-debug.log", "a") as f:
                import datetime
                f.write(f"\n=== {datetime.datetime.now()} ===\n")
                f.write(f"Repo: {repo.name}\n")
                f.write(f"Local path: {repo.local_path}\n")
                f.write(f"Claude command: {claude_command}\n")
                f.write(f"Full command: {cmd}\n")

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

    except FileNotFoundError as e:
        error_msg = f"Error: File not found - {e.filename}"
        if config.data.get("debug", False):
            with open("/tmp/claude-launch-debug.log", "a") as f:
                f.write(f"ERROR: {error_msg}\n")
        return error_msg
    except Exception as e:
        error_msg = f"Error launching: {e}"
        if config.data.get("debug", False):
            with open("/tmp/claude-launch-debug.log", "a") as f:
                import traceback
                f.write(f"ERROR: {error_msg}\n")
                f.write(traceback.format_exc())
        return error_msg


def check_repo_local(repo_name: str, base_path: str = "/home/adam/Code") -> str | None:
    """Check if a repository exists locally.

    Returns the full path if it exists, None otherwise.
    """
    repo_path = Path(base_path) / repo_name
    if repo_path.exists() and repo_path.is_dir():
        return str(repo_path)
    return None
