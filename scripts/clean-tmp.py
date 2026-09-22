#!/usr/bin/env python3
"""
Clean agent scratch under the repo-root `.tmp/` (stdlib only).

Applies the rules in support/multi-agent.md section Agent Scratch:

- `.tmp/worktrees/*`: a registered worktree is removed only when it has no uncommitted
  or untracked changes AND its work is merged - HEAD is an ancestor of the base branch,
  or `gh` reports a merged PR whose head commit is HEAD (squash merges). Never forces.
  Locked worktrees and unregistered directories are reported, not touched.
- `git worktree prune` for registrations whose directory is already gone.
- `.tmp/sessions/*`: removed when nothing inside changed for --session-days days, and only
  once no worktree remains under `.tmp/worktrees/` (open work may still need its logs).
- `.tmp/golden-path-runs/*` (maintainer repo): keep the newest --keep-runs reports and
  delete each pruned run's recorded `workboard-gp-*` workspace with it, only when that
  workspace sits inside the system temp folder or `.tmp/` and no kept run references it.

Dry run by default; pass --apply to act. Run it after the merge is verified, not while
workers are still running.

Usage:
    python scripts/clean-tmp.py
    python scripts/clean-tmp.py --apply
    python scripts/clean-tmp.py --apply --base origin/main
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

WORKSPACE_LINE = re.compile(r"^- workspace: (.+)$", re.MULTILINE)
GOLDEN_WORKSPACE_PREFIX = "workboard-gp-"


def git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True, encoding="utf-8", errors="replace"
    )


def main_checkout(start: Path) -> Path:
    """Resolve the main checkout even when invoked from inside a worktree."""
    proc = git(start, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if proc.returncode != 0:
        raise SystemExit(f"[fail] not inside a git repository: {start}\n{proc.stderr.strip()}")
    return Path(proc.stdout.strip()).resolve().parent


def resolve_base(root: Path, explicit: str | None) -> str:
    if explicit:
        if git(root, "rev-parse", "--verify", "--quiet", f"{explicit}^{{commit}}").returncode != 0:
            raise SystemExit(f"[fail] --base {explicit} does not resolve to a commit")
        return explicit
    proc = git(root, "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD")
    if proc.returncode != 0 or not proc.stdout.strip():
        raise SystemExit(
            "[fail] cannot resolve the default branch (origin/HEAD unset); pass --base <ref> "
            "or run `git remote set-head origin --auto`"
        )
    return proc.stdout.strip()


def list_worktrees(root: Path) -> list[dict[str, str]]:
    proc = git(root, "worktree", "list", "--porcelain")
    if proc.returncode != 0:
        raise SystemExit(f"[fail] git worktree list failed: {proc.stderr.strip()}")
    entries: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for line in proc.stdout.splitlines():
        if not line:
            if current:
                entries.append(current)
                current = {}
            continue
        key, _, value = line.partition(" ")
        current[key] = value
    if current:
        entries.append(current)
    return entries


def is_under(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
    except ValueError:
        return False
    return True


def merged_reason(root: Path, head: str, branch: str | None, base: str, use_gh: bool) -> str | None:
    if git(root, "merge-base", "--is-ancestor", head, base).returncode == 0:
        return f"ancestor of {base}"
    if not (use_gh and branch and shutil.which("gh")):
        return None
    proc = subprocess.run(
        ["gh", "pr", "list", "--head", branch, "--state", "merged", "--json", "headRefOid", "--limit", "20"],
        cwd=str(root), capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if proc.returncode != 0:
        print(f"  [warn] gh pr list failed for {branch}; treating as unmerged: {proc.stderr.strip()}")
        return None
    if any(pr.get("headRefOid") == head for pr in json.loads(proc.stdout or "[]")):
        return "merged PR head (squash/rebase merge)"
    return None


def clean_worktrees(root: Path, base: str, apply: bool, use_gh: bool) -> tuple[int, int]:
    """Returns (failures, worktrees still present under .tmp/worktrees)."""
    scratch = root / ".tmp" / "worktrees"
    failures = 0
    remaining = 0
    registered: set[str] = set()
    for entry in list_worktrees(root):
        path = Path(entry["worktree"])
        if not is_under(path, scratch):
            continue
        registered.add(os.path.normcase(str(path.resolve())))
        rel = path.resolve().relative_to(root).as_posix()
        if "prunable" in entry:
            print(f"  [prune] {rel} (directory missing)")
            continue
        remaining += 1
        if "locked" in entry:
            print(f"  [keep]  {rel} (locked)")
            continue
        status = git(path, "status", "--porcelain")
        if status.returncode != 0:
            print(f"  [keep]  {rel} (git status failed: {status.stderr.strip()})")
            continue
        if status.stdout.strip():
            print(f"  [keep]  {rel} (uncommitted or untracked changes)")
            continue
        branch = entry.get("branch", "").removeprefix("refs/heads/") or None
        reason = merged_reason(root, entry["HEAD"], branch, base, use_gh)
        if not reason:
            print(f"  [keep]  {rel} (not merged into {base})")
            continue
        if not apply:
            print(f"  [would remove] {rel} ({reason})")
            continue
        removed = git(root, "worktree", "remove", str(path))
        if removed.returncode != 0:
            print(f"  [fail]  {rel}: {removed.stderr.strip()}")
            failures += 1
        else:
            remaining -= 1
            print(f"  [removed] {rel} ({reason})")
    if scratch.is_dir():
        for child in sorted(scratch.iterdir()):
            if child.is_dir() and os.path.normcase(str(child.resolve())) not in registered:
                remaining += 1
                print(f"  [keep]  {child.relative_to(root).as_posix()} (not a registered worktree; inspect and delete by hand)")
    if apply:
        pruned = git(root, "worktree", "prune")
        if pruned.returncode != 0:
            print(f"  [fail]  git worktree prune: {pruned.stderr.strip()}")
            failures += 1
    return failures, remaining


def _make_writable_and_retry(func, path, _exc) -> None:
    # Git object files are read-only on Windows; rmtree cannot unlink them otherwise.
    os.chmod(path, stat.S_IWRITE)
    func(path)


def remove_tree(path: Path) -> None:
    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=_make_writable_and_retry)
    else:
        shutil.rmtree(path, onerror=_make_writable_and_retry)


def newest_mtime(path: Path) -> float:
    return max((p.stat().st_mtime for p in path.rglob("*")), default=path.stat().st_mtime)


def clean_sessions(root: Path, days: int, apply: bool, open_worktrees: int) -> int:
    base = root / ".tmp" / "sessions"
    if not base.is_dir():
        return 0
    if open_worktrees:
        # Sessions are not linked to worktrees, so any open worktree may still need its logs and handoff.
        print(f"  [keep]  all sessions ({open_worktrees} worktree(s) still present under .tmp/worktrees)")
        return 0
    cutoff = time.time() - days * 86400
    failures = 0
    for child in sorted(p for p in base.iterdir() if p.is_dir()):
        rel = child.relative_to(root).as_posix()
        if newest_mtime(child) >= cutoff:
            print(f"  [keep]  {rel} (changed within {days} day(s))")
            continue
        if not apply:
            print(f"  [would remove] {rel}")
            continue
        try:
            remove_tree(child)
            print(f"  [removed] {rel}")
        except OSError as exc:
            print(f"  [fail]  {rel}: {exc}")
            failures += 1
    return failures


def recorded_workspace(run_dir: Path, root: Path) -> Path | None:
    """The run's workspace, only when it is a `workboard-gp-*` dir inside the system temp folder or .tmp/."""
    report = run_dir / "report.md"
    if not report.is_file():
        return None
    match = WORKSPACE_LINE.search(report.read_text(encoding="utf-8"))
    if not match:
        return None
    workspace = Path(match.group(1).strip())
    if not (workspace.name.startswith(GOLDEN_WORKSPACE_PREFIX) and workspace.is_dir()):
        return None
    allowed = (Path(tempfile.gettempdir()), root / ".tmp")
    return workspace if any(is_under(workspace, parent) for parent in allowed) else None


def clean_golden_path_runs(root: Path, keep: int, apply: bool) -> int:
    base = root / ".tmp" / "golden-path-runs"
    if not base.is_dir():
        return 0
    runs = sorted((p for p in base.iterdir() if p.is_dir()), key=lambda p: p.name, reverse=True)
    failures = 0
    # Resumed runs share a workspace; one still referenced by a kept run must survive.
    handled = {os.path.normcase(str(w.resolve())) for w in (recorded_workspace(r, root) for r in runs[:keep]) if w}
    for run in runs[:keep]:
        print(f"  [keep]  {run.relative_to(root).as_posix()} (newest {keep})")
    for run in runs[keep:]:
        targets = [run]
        workspace = recorded_workspace(run, root)
        if workspace and os.path.normcase(str(workspace.resolve())) not in handled:
            handled.add(os.path.normcase(str(workspace.resolve())))
            targets.append(workspace)
        for target in targets:
            label = target.resolve().relative_to(root).as_posix() if is_under(target, root) else str(target)
            if not apply:
                print(f"  [would remove] {label}")
                continue
            try:
                remove_tree(target)
                print(f"  [removed] {label}")
            except OSError as exc:
                print(f"  [fail]  {label}: {exc}")
                failures += 1
    return failures


def non_negative(value: str) -> int:
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError(f"must be >= 0, got {number}")
    return number


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Clean agent scratch under the repo-root .tmp/ (dry run by default).")
    p.add_argument("--apply", action="store_true", help="act; without it only report")
    p.add_argument("--root", type=Path, default=Path.cwd(), help="any path inside the repo; default cwd")
    p.add_argument("--base", default=None, help="merge base ref; default origin/HEAD")
    p.add_argument("--no-gh", action="store_true", help="skip the gh merged-PR check (squash merges then stay)")
    p.add_argument("--session-days", type=non_negative, default=7)
    p.add_argument("--keep-runs", type=non_negative, default=5)
    args = p.parse_args(argv)

    root = main_checkout(args.root)
    base = resolve_base(root, args.base)
    mode = "apply" if args.apply else "dry run"
    print(f"== clean-tmp ({mode}) root={root} base={base} ==")
    print("worktrees:")
    failures, open_worktrees = clean_worktrees(root, base, args.apply, use_gh=not args.no_gh)
    print("sessions:")
    failures += clean_sessions(root, args.session_days, args.apply, open_worktrees)
    print("golden-path runs:")
    failures += clean_golden_path_runs(root, args.keep_runs, args.apply)
    if failures:
        print(f"[fail] {failures} item(s) could not be removed")
        return 1
    print("[ok] done" if args.apply else "[ok] dry run complete; re-run with --apply to act")
    return 0


if __name__ == "__main__":
    sys.exit(main())
