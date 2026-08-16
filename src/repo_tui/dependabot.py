"""Bulk-merge Dependabot PRs across the configured repo list."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .models import RepoOverview


@dataclass
class MergeResult:
    """Outcome of attempting to merge a single PR."""

    pr_number: int
    pr_title: str
    success: bool
    reason: str


@dataclass
class RepoProgress:
    """Progress update emitted as each repo is processed."""

    repo_name: str
    phase: str  # "scanning" | "done"
    results: list[MergeResult] = field(default_factory=list)
    error: str | None = None  # Set when the repo could not be read at all


def _is_dependabot_author(author: str | None) -> bool:
    return "dependabot" in (author or "").lower()


def _summarize_checks(rollup: Any) -> str | None:
    """Collapse a statusCheckRollup blob into SUCCESS/FAILURE/PENDING."""
    contexts: list[Any] = []
    if isinstance(rollup, dict):
        contexts = rollup.get("contexts", []) or []
    elif isinstance(rollup, list):
        contexts = rollup
    if not contexts:
        return None

    statuses = [c.get("state") or c.get("conclusion") for c in contexts if isinstance(c, dict)]
    if any(s in ("FAILURE", "failure", "TIMED_OUT") for s in statuses):
        return "FAILURE"
    if any(s in ("PENDING", "pending", "IN_PROGRESS") for s in statuses):
        return "PENDING"
    non_empty = [s for s in statuses if s]
    if non_empty and all(s in ("SUCCESS", "success") for s in non_empty):
        return "SUCCESS"
    return None


async def _list_dependabot_prs(owner: str, repo: str) -> list[dict[str, Any]] | None:
    """Live-query open Dependabot PRs for a repo.

    Returns None when the listing itself failed — an empty list means "no open
    Dependabot PRs", and reporting that for a failed `gh` call would tell the
    user a repo is up to date when it may not be.
    """
    proc = await asyncio.create_subprocess_exec(
        "gh",
        "pr",
        "list",
        "--repo",
        f"{owner}/{repo}",
        "--author",
        "app/dependabot",
        "--state",
        "open",
        "--json",
        "number,title,mergeable,statusCheckRollup,headRefName",
        "--limit",
        "100",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    if proc.returncode != 0:
        return None
    try:
        data = json.loads(stdout.decode())
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, list) else None


def _shorten_reason(stderr_text: str, exit_code: int) -> str:
    """Extract a human-friendly reason from gh's stderr."""
    msg = stderr_text.strip()
    lowered = msg.lower()

    if "is not mergeable" in lowered or "merge conflict" in lowered:
        return "merge conflicts"
    if "required status check" in lowered and "fail" in lowered:
        return "required checks failing"
    if "required status check" in lowered:
        return "required checks not yet passed"
    if "review" in lowered and "required" in lowered:
        return "review required"
    if "branch protection" in lowered:
        return "blocked by branch protection"
    if "not allowed" in lowered and "squash" in lowered:
        return "squash merge not enabled on this repo"
    if "is in clean status" in lowered or "is in dirty status" in lowered:
        return "PR is not in mergeable status"

    first_line = msg.split("\n", 1)[0] if msg else ""
    return first_line[:120] if first_line else f"gh merge exited {exit_code}"


async def _merge_pr(owner: str, repo: str, pr_number: int) -> tuple[bool, str]:
    """Attempt to squash-merge a PR. Returns (success, reason)."""
    proc = await asyncio.create_subprocess_exec(
        "gh",
        "pr",
        "merge",
        str(pr_number),
        "--repo",
        f"{owner}/{repo}",
        "--squash",
        "--delete-branch",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode == 0:
        return (True, "merged")

    combined = (stderr.decode() if stderr else "") or (stdout.decode() if stdout else "")
    return (False, _shorten_reason(combined, proc.returncode or 0))


async def merge_all_dependabot_prs(
    repos: list[RepoOverview],
) -> AsyncIterator[RepoProgress]:
    """Iterate repos, merge Dependabot PRs, yield progress per repo.

    Strategy: skip repos with no cached Dependabot PRs (fast path). For the
    rest, live-query gh for the latest PR state, pre-flight each PR against
    conflicts/failing/pending checks, then attempt a squash merge. Never
    rebases or posts comments — purely reports what happened.
    """
    for repo in repos:
        yield RepoProgress(repo.name, "scanning")

        has_cached = any(_is_dependabot_author(pr.author) for pr in (repo.pull_requests or []))
        if not has_cached:
            yield RepoProgress(repo.name, "done", [])
            continue

        prs = await _list_dependabot_prs(repo.owner, repo.name)
        if prs is None:
            yield RepoProgress(repo.name, "done", [], error="could not list PRs (gh failed)")
            continue
        if not prs:
            yield RepoProgress(repo.name, "done", [])
            continue

        results: list[MergeResult] = []
        for pr in prs:
            pr_number = pr.get("number")
            pr_title = pr.get("title", "")
            if not isinstance(pr_number, int):
                continue

            mergeable = pr.get("mergeable")
            checks = _summarize_checks(pr.get("statusCheckRollup"))

            if mergeable == "CONFLICTING":
                results.append(MergeResult(pr_number, pr_title, False, "has merge conflicts"))
                continue
            if checks == "FAILURE":
                results.append(MergeResult(pr_number, pr_title, False, "CI checks failing"))
                continue
            if checks == "PENDING":
                results.append(MergeResult(pr_number, pr_title, False, "CI checks still pending"))
                continue

            success, reason = await _merge_pr(repo.owner, repo.name, pr_number)
            results.append(MergeResult(pr_number, pr_title, success, reason))

        yield RepoProgress(repo.name, "done", results)
