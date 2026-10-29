#!/usr/bin/env python3
"""
Refresh the vendored skills under vendor/ from a local checkout of their source repo.
Maintainer-only: it lives outside the shipped payload so installed apps never rewrite vendor/.

vendor/SOURCES.json maps each vendored file to its path in the source repo and records
the source commit and each copy's SHA-256 (line endings normalized to LF).
validate-instructions.py fails when a vendored file no longer matches its recorded hash,
so vendored files change only through this script, never by hand.

    python maintenance/sync-vendor.py --from ../workstation           # copy and re-record
    python maintenance/sync-vendor.py --from ../workstation --check   # report staleness only

Exit code 0 when synced (or, with --check, current), 1 otherwise.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCES = REPO_ROOT / "vendor" / "SOURCES.json"


def normalized_bytes(path: Path) -> bytes:
    return path.read_bytes().replace(b"\r\n", b"\n")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def names_repository(url: str, repository: str) -> bool:
    """True when url is https://host/owner/repo, git@host:owner/repo or a local path ending in
    owner/repo for repository "owner/repo"; a lookalike owner such as notowner/repo is not."""
    tail = url.strip().replace("\\", "/").replace(":", "/").lower().rstrip("/").removesuffix(".git")
    return "/".join(tail.rsplit("/", 2)[-2:]) == repository.lower()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--from", dest="source", required=True, help="local checkout of the source repo")
    parser.add_argument("--check", action="store_true", help="report vendored files that differ from the source; write nothing")
    args = parser.parse_args()

    source_root = Path(args.source).resolve()
    sources = json.loads(SOURCES.read_text(encoding="utf-8"))
    entries: dict[str, dict] = sources["files"]

    missing = [e["path"] for e in entries.values() if not (source_root / e["path"]).is_file()]
    if missing:
        print(f"source files missing under {source_root}: {missing}")
        return 1

    if args.check:
        stale = []
        for rel, entry in entries.items():
            local = REPO_ROOT / rel
            upstream = sha256(normalized_bytes(source_root / entry["path"]))
            if not local.is_file() or sha256(normalized_bytes(local)) != upstream:
                stale.append(rel)
                print(f"stale: {rel} differs from {entry['path']} - run without --check to refresh")
        if not stale:
            print(f"vendor/ matches {source_root} for {len(entries)} file(s)")
        return 1 if stale else 0

    def git(*git_args: str) -> bytes | None:
        proc = subprocess.run(["git", "-C", str(source_root), *git_args], capture_output=True)
        if proc.returncode != 0:
            print(f"git {' '.join(git_args[:2])} failed in {source_root}: {proc.stderr.decode(errors='replace').strip()}")
            return None
        return proc.stdout

    # The recorded commit must reproduce the copied bytes and stay fetchable from the recorded
    # repository: content is read from that commit, never the working tree, and uncommitted
    # edits or a commit missing from that repository's default branch (fetched now, so a stale
    # or deleted branch cannot vouch for it) are refused.
    dirty = git("status", "--porcelain", "--", *[e["path"] for e in entries.values()])
    commit = git("rev-parse", "HEAD")
    remotes = git("remote")
    if dirty is None or commit is None or remotes is None:
        return 1
    if dirty.strip():
        print(f"source files have uncommitted changes; commit them first:\n{dirty.decode(errors='replace')}")
        return 1
    commit_id = commit.decode().strip()
    published = False
    for name in remotes.decode().split():
        url = git("remote", "get-url", name)
        if url is None:
            return 1
        if not names_repository(url.decode(), sources["repository"]):
            continue
        if git("fetch", "-q", name, "HEAD") is None:
            return 1
        ancestry = subprocess.run(["git", "-C", str(source_root), "merge-base", "--is-ancestor", commit_id, "FETCH_HEAD"])
        if ancestry.returncode == 0:
            published = True
            break
    if not published:
        print(f"source HEAD {commit_id} is not on the default branch of a remote for {sources['repository']}; merge and push it there first")
        return 1

    # Read every file before writing any, so a failed read leaves vendor/ and the manifest consistent.
    contents = {}
    for rel, entry in entries.items():
        content = git("show", f"{commit_id}:{entry['path']}")
        if content is None:
            return 1
        contents[rel] = content.replace(b"\r\n", b"\n")
    for rel, data in contents.items():
        dest = REPO_ROOT / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        entries[rel]["sha256"] = sha256(data)
    sources["commit"] = commit_id
    SOURCES.write_text(json.dumps(sources, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"synced {len(entries)} file(s) from {source_root} at {commit_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
