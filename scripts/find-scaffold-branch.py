#!/usr/bin/env python3
"""Find the live scaffold branch for the Git Checkpoint Protocol (support/OPERATIONS.md, start step 2).

Every `scaffold/*` name, local or on `origin`, is classified by its pull requests from this repository
(forks are ignored): an open PR, or no PR yet -> live; otherwise the newest PR decides: MERGED with no
commits past the merged head -> merged (the session deletes its local copy, if any, per the protocol's
exemption); CLOSED, MERGED with later commits, or a deciding PR into a branch other than the default
-> ask. One live name is the answer, none means no live branch, two or more means ask. A repository
without a GitHub `origin`, a missing `git` or `gh`, or a query that fails also means ask.

Prints one JSON object: {"result": "live" | "none" | "ask", "branch": str | null,
"merged": [{"name": str, "headRefOid": str}], "reason": str}. Exit code 0 for live or none, 2 for ask.

Usage (from the app repo root):
    python .instructions/scripts/find-scaffold-branch.py
"""

from __future__ import annotations

import json
import os
import random
import re
import signal
import subprocess
import sys
import time
from typing import Callable

Runner = Callable[[list[str]], subprocess.CompletedProcess]

# Transient network faults worth another try; anything else fails fast to ask. Rate limits (HTTP 429,
# "rate limit") are not retried: gh exposes no Retry-After, and GitHub's limits outlast a short backoff.
TRANSIENT = re.compile(r"timed? ?out|connection (reset|refused)|could not resolve host|"
                       r"temporarily unavailable|(HTTP|error:) 50[0234]\b|TLS handshake", re.IGNORECASE)
RATE_LIMITED = re.compile(r"rate limit|\b429\b", re.IGNORECASE)
ATTEMPTS = 3
TIMEOUT_SECONDS = 120
# English messages for the classifier, and no credential prompt (terminal or Git Credential Manager)
# that would hang a headless session.
ENV = {**os.environ, "LC_ALL": "C", "LANG": "C", "GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never",
       "GH_PROMPT_DISABLED": "1"}
GITHUB_REMOTE = re.compile(r"^(?:https://(?:[^@/\s]+@)?github\.com/|(?:ssh://)?git@github\.com[:/])"
                           r"(?P<repo>[^/\s]+/[^/\s]+?)(?:\.git)?/?$")
# An explicit refspec, so a single-branch clone still sees (and prunes) every scaffold branch on origin.
SCAFFOLD_REFSPEC = "+refs/heads/scaffold/*:refs/remotes/origin/scaffold/*"


def kill_tree(pid: int) -> None:
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)], capture_output=True)
    else:
        os.killpg(pid, signal.SIGKILL)


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    """Run one command with a timeout that ends its whole process tree.

    git's helpers (git-remote-https, a credential manager) inherit the output pipes, so killing git
    alone would leave the read waiting on them.
    """
    try:
        proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, encoding="utf-8", errors="replace", env=ENV,
                                start_new_session=os.name != "nt")
    except FileNotFoundError:
        return subprocess.CompletedProcess(cmd, 127, "", f"{cmd[0]} not found on PATH")
    try:
        out, err = proc.communicate(timeout=TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        kill_tree(proc.pid)
        try:
            proc.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            pass  # A process outside the tree still holds a pipe; the result is the timeout either way.
        return subprocess.CompletedProcess(cmd, 124, "", f"timed out after {TIMEOUT_SECONDS}s")
    return subprocess.CompletedProcess(cmd, proc.returncode, out, err)


def newest(prs: list[dict]) -> dict | None:
    return max(prs, key=lambda p: p["createdAt"], default=None)


def run_with_retry(runner: Runner, cmd: list[str], sleep: Callable[[float], None] = time.sleep) -> subprocess.CompletedProcess:
    """Run a read-only network command, retrying only transient failures with exponential backoff and jitter."""
    for attempt in range(1, ATTEMPTS + 1):
        proc = runner(cmd)
        stderr = proc.stderr or ""
        if (proc.returncode == 0 or attempt == ATTEMPTS
                or not TRANSIENT.search(stderr) or RATE_LIMITED.search(stderr)):
            return proc
        delay = 2 ** attempt + random.uniform(0, 1)
        print(f"retry {attempt}/{ATTEMPTS - 1} in {delay:.1f}s: {' '.join(cmd)}: {stderr.strip()}", file=sys.stderr)
        sleep(delay)
    raise AssertionError("unreachable")


def find(runner: Runner = run, sleep: Callable[[float], None] = time.sleep) -> dict:
    merged: list[dict] = []

    def ask(reason: str) -> dict:
        return {"result": "ask", "branch": None, "merged": merged, "reason": reason}

    def failed(proc: subprocess.CompletedProcess, what: str) -> dict:
        return ask(f"{what} failed: {(proc.stderr or '').strip()}")

    url = runner(["git", "remote", "get-url", "origin"])
    if url.returncode != 0:
        return failed(url, "git remote get-url origin (the protocol assumes a GitHub origin)")
    match = GITHUB_REMOTE.search(url.stdout.strip())
    if not match:
        # The URL itself is not echoed: it can carry a token in its userinfo.
        return ask("origin is not a GitHub repository (a github.com https or ssh URL)")
    repo = match.group("repo")
    fetch = run_with_retry(runner, ["git", "fetch", "--prune", "origin", SCAFFOLD_REFSPEC], sleep)
    if fetch.returncode != 0:
        return failed(fetch, "git fetch")
    default = run_with_retry(runner, ["gh", "repo", "view", repo, "--json", "defaultBranchRef",
                                      "--jq", ".defaultBranchRef.name"], sleep)
    if default.returncode != 0 or not default.stdout.strip():
        return failed(default, "gh repo view")
    base = default.stdout.strip()
    refs = runner(["git", "for-each-ref", "--format=%(refname)", "refs/heads/scaffold/", "refs/remotes/origin/scaffold/"])
    if refs.returncode != 0:
        return failed(refs, "git for-each-ref")
    by_name: dict[str, list[str]] = {}
    for ref in refs.stdout.split():
        by_name.setdefault(re.sub(r"^refs/(heads|remotes/origin)/", "", ref), []).append(ref)

    live: list[str] = []
    for name in sorted(by_name):
        proc = run_with_retry(runner, ["gh", "pr", "list", "--repo", repo, "--head", name, "--state", "all",
                                       "--limit", "100",
                                       "--json", "state,createdAt,isCrossRepository,headRefOid,baseRefName"], sleep)
        if proc.returncode != 0:
            return failed(proc, f"gh pr list for {name}")
        try:
            prs = [p for p in json.loads(proc.stdout or "[]") if not p["isCrossRepository"]]
            deciding = newest([p for p in prs if p["state"] == "OPEN"]) or newest(prs)
            target = deciding["baseRefName"] if deciding else base
        except (ValueError, KeyError, TypeError) as exc:
            return ask(f"gh pr list for {name} returned unreadable output: {exc}")
        state = deciding["state"] if deciding else "NONE"
        if target != base:
            return ask(f"{name}: its {state} PR targets {target}, not the default branch {base}")
        if state in ("OPEN", "NONE"):
            live.append(name)
        elif state == "MERGED":
            oid = deciding["headRefOid"]
            for ref in by_name[name]:
                ahead = runner(["git", "rev-list", "--count", f"{oid}..{ref}"])
                if ahead.returncode != 0:
                    return failed(ahead, f"git rev-list for {ref} (is the merged head {oid} in this clone?)")
                if ahead.stdout.strip() != "0":
                    return ask(f"{ref} has commits after its merged PR's head {oid}")
            merged.append({"name": name, "headRefOid": oid})
        else:
            return ask(f"{name}: its newest PR is {state}")
    if len(live) > 1:
        return ask(f"more than one live scaffold branch: {', '.join(live)}")
    if live:
        return {"result": "live", "branch": live[0], "merged": merged, "reason": "open PR or none yet"}
    return {"result": "none", "branch": None, "merged": merged, "reason": "no scaffold/* branch without a merged PR"}


def main() -> int:
    outcome = find()
    print(json.dumps(outcome))
    return 2 if outcome["result"] == "ask" else 0


if __name__ == "__main__":
    sys.exit(main())
