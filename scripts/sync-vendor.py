#!/usr/bin/env python3
"""
Refresh the vendored skills under vendor/ from a local checkout of their source repo.

vendor/SOURCES.json maps each vendored file to its path in the source repo and records
the source commit and each copy's SHA-256 (line endings normalized to LF).
validate-instructions.py fails when a vendored file no longer matches its recorded hash,
so vendored files change only through this script, never by hand.

    python scripts/sync-vendor.py --from ../workstation           # copy and re-record
    python scripts/sync-vendor.py --from ../workstation --check   # report staleness only

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
        stale = [rel for rel, e in entries.items() if sha256(normalized_bytes(source_root / e["path"])) != e["sha256"]]
        for rel in stale:
            print(f"stale: {rel} differs from {entries[rel]['path']} - run without --check to refresh")
        if not stale:
            print(f"vendor/ matches {source_root} for {len(entries)} file(s)")
        return 1 if stale else 0

    # The recorded commit must describe the copied content, so uncommitted source edits are refused.
    paths = [e["path"] for e in entries.values()]
    dirty = subprocess.run(
        ["git", "-C", str(source_root), "status", "--porcelain", "--", *paths],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    if dirty:
        print(f"source files have uncommitted changes; commit them first:\n{dirty}")
        return 1
    commit = subprocess.run(
        ["git", "-C", str(source_root), "rev-parse", "HEAD"], capture_output=True, text=True, check=True,
    ).stdout.strip()

    for rel, entry in entries.items():
        data = normalized_bytes(source_root / entry["path"])
        dest = REPO_ROOT / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        entry["sha256"] = sha256(data)
    sources["commit"] = commit
    SOURCES.write_text(json.dumps(sources, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"synced {len(entries)} file(s) from {source_root} at {commit}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
