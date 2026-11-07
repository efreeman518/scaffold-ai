#!/usr/bin/env python3
"""Find the live scaffold branch for the Git Checkpoint Protocol (support/OPERATIONS.md, start step 2).

Every `scaffold/*` name, local or on `origin`, is classified by its pull request:
open, or no PR yet -> live; MERGED -> merged (the session deletes the local copy per the
protocol's exemption); CLOSED -> ask. One live name is the answer, none means no live branch,
two or more means ask. A repository without `origin`, or a `gh` query that fails, also means ask.

Prints one JSON object: {"result": "live" | "none" | "ask", "branch": str | null,
"merged": [names], "reason": str}. Exit code 0 for live or none, 2 for ask.

Usage (from the app repo root):
    python .instructions/scripts/find-scaffold-branch.py
"""

from __future__ import annotations

import json
import random
import re
import subprocess
import sys
import time
from typing import Callable

Runner = Callable[[list[str]], subprocess.CompletedProcess]

# Transient network faults worth one more try; anything else (auth, unknown branch) fails fast.
TRANSIENT = re.compile(r"timed? ?out|connection (reset|refused)|could not resolve host|"
                       r"temporarily unavailable|\b50[234]\b|rate limit|TLS handshake", re.IGNORECASE)
ATTEMPTS = 3


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True)


def run_with_retry(runner: Runner, cmd: list[str], sleep: Callable[[float], None] = time.sleep) -> subprocess.CompletedProcess:
    """Run a network command, retrying only transient failures with exponential backoff and jitter."""
    for attempt in range(1, ATTEMPTS + 1):
        proc = runner(cmd)
        if proc.returncode == 0 or attempt == ATTEMPTS or not TRANSIENT.search(proc.stderr or ""):
            return proc
        delay = 2 ** attempt + random.uniform(0, 1)
        print(f"retry {attempt}/{ATTEMPTS - 1} in {delay:.1f}s: {' '.join(cmd)}: {proc.stderr.strip()}", file=sys.stderr)
        sleep(delay)
    raise AssertionError("unreachable")


def find(runner: Runner = run, sleep: Callable[[float], None] = time.sleep) -> dict:
    def ask(reason: str, merged: list[str] | None = None) -> dict:
        return {"result": "ask", "branch": None, "merged": merged or [], "reason": reason}

    remotes = runner(["git", "remote"])
    if remotes.returncode != 0:
        return ask(f"git remote failed: {remotes.stderr.strip()}")
    if "origin" not in remotes.stdout.split():
        return ask("no origin remote: the protocol assumes a GitHub origin")
    fetch = run_with_retry(runner, ["git", "fetch", "--prune", "origin"], sleep)
    if fetch.returncode != 0:
        return ask(f"git fetch failed: {fetch.stderr.strip()}")
    refs = runner(["git", "for-each-ref", "--format=%(refname)", "refs/heads/scaffold/", "refs/remotes/origin/scaffold/"])
    if refs.returncode != 0:
        return ask(f"git for-each-ref failed: {refs.stderr.strip()}")
    names = sorted({re.sub(r"^refs/(heads|remotes/origin)/", "", r) for r in refs.stdout.split()})

    live: list[str] = []
    merged: list[str] = []
    for name in names:
        proc = run_with_retry(runner, ["gh", "pr", "list", "--head", name, "--state", "all",
                                       "--json", "state", "--limit", "1"], sleep)
        if proc.returncode != 0:
            return ask(f"gh pr list for {name} failed: {proc.stderr.strip()}", merged)
        prs = json.loads(proc.stdout or "[]")
        state = prs[0]["state"] if prs else "NONE"
        if state in ("OPEN", "NONE"):
            live.append(name)
        elif state == "MERGED":
            merged.append(name)
        else:
            return ask(f"{name}: its PR is {state}", merged)
    if len(live) > 1:
        return ask(f"more than one live scaffold branch: {', '.join(live)}", merged)
    if live:
        return {"result": "live", "branch": live[0], "merged": merged, "reason": "open PR or none yet"}
    return {"result": "none", "branch": None, "merged": merged, "reason": "no scaffold/* branch without a merged PR"}


def main() -> int:
    outcome = find()
    print(json.dumps(outcome))
    return 2 if outcome["result"] == "ask" else 0


if __name__ == "__main__":
    sys.exit(main())
