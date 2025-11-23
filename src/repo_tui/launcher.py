"""Windows Terminal + Claude Code launcher."""

import subprocess
import sys
from typing import Optional

from .models import RepoOverview, Issue


def reset_terminal_modes() -> None:
    """Reset terminal modes that might leak to child processes."""
    # Disable mouse tracking modes that Textual enables
    # These escape codes turn off various mouse reporting modes
    sys.stdout.write('\x1b[?1000l')  # Disable mouse click tracking
    sys.stdout.write('\x1b[?1002l')  # Disable mouse drag tracking
    sys.stdout.write('\x1b[?1003l')  # Disable all mouse tracking
    sys.stdout.write('\x1b[?1006l')  # Disable SGR mouse mode
    sys.stdout.flush()


def build_claude_prompt(issue: Optional[Issue] = None) -> str:
    """Build the prompt string for Claude Code."""
    if issue:
        return f"/StartOfTheDay then work on issue #{issue.number}: {issue.title}"
    else:
        return "/StartOfTheDay"


def build_wt_command(repo: RepoOverview, issue: Optional[Issue] = None) -> list:
    r"""
    Build Windows Terminal command to launch Claude Code.

    Command structure:
    wt.exe -w 0 nt --title "repo-name" --suppressApplicationTitle \
      -d "\\wsl$\Ubuntu\path\to\repo" \
      wsl.exe -d Ubuntu -- bash -c "reset && claude prompt"
    """
    prompt = build_claude_prompt(issue)

    # WSL path for Windows Terminal (e.g., \\wsl$\Ubuntu\home\adam\Code\repo)
    wsl_path = repo.local_path.replace("/home/", r"\\wsl$\Ubuntu\home\\")

    # Escape single quotes in prompt for bash
    escaped_prompt = prompt.replace("'", "'\\''")

    # Build command parts
    # Use full path to claude since PATH may not be set in new terminal
    # Wrap in bash -c with 'reset' to clear any inherited terminal state
    cmd = [
        "wt.exe",
        "-w", "0",                          # Current window
        "nt",                                # New tab
        "--title", repo.name,                # Tab title
        "--suppressApplicationTitle",        # Keep our title
        "-d", wsl_path,                      # Starting directory
        "wsl.exe",
        "-d", "Ubuntu",
        "--",
        "bash", "-c",
        f"reset && /home/adam/.claude/local/claude '{escaped_prompt}'"
    ]

    return cmd


def launch_claude(repo: RepoOverview, issue: Optional[Issue] = None) -> str:
    """
    Launch Claude Code in a new Windows Terminal tab.

    Returns a status message.
    """
    if not repo.local_path:
        return f"Repo not found locally: ~/Code/{repo.name}"

    try:
        cmd = build_wt_command(repo, issue)

        # Launch asynchronously (don't wait for it)
        subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True
        )

        if issue:
            return f"Launched Claude for {repo.name} #{issue.number}"
        else:
            return f"Launched Claude for {repo.name}"

    except FileNotFoundError:
        return "Error: wt.exe not found. Is Windows Terminal installed?"
    except Exception as e:
        return f"Error launching: {e}"


def check_repo_local(repo_name: str, base_path: str = "/home/adam/Code") -> Optional[str]:
    """
    Check if a repository exists locally.

    Returns the full path if it exists, None otherwise.
    """
    from pathlib import Path

    repo_path = Path(base_path) / repo_name
    if repo_path.exists() and repo_path.is_dir():
        return str(repo_path)
    return None
