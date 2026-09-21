#!/usr/bin/env python3
"""Fail when the packaged Web UI bundle drifts from the frontend build.

``src/worktree_review/server/static/`` is a gitignored copy of
``frontend/dist`` produced by ``scripts/sync_frontend_dist.py`` at packaging
time. This check compares both trees byte-for-byte so a stale or hand-edited
bundle can never slip into a wheel.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIST = REPO_ROOT / "frontend" / "dist"
PACKAGE_STATIC = REPO_ROOT / "src" / "worktree_review" / "server" / "static"


def _tree_hashes(root: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            relative = path.relative_to(root).as_posix()
            hashes[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashes


def main() -> int:
    if not (SOURCE_DIST / "index.html").is_file():
        print(f"frontend build missing at {SOURCE_DIST}", file=sys.stderr)
        return 1
    if not (PACKAGE_STATIC / "index.html").is_file():
        print(
            f"packaged static bundle missing at {PACKAGE_STATIC}; "
            "run scripts/sync_frontend_dist.py",
            file=sys.stderr,
        )
        return 1
    source = _tree_hashes(SOURCE_DIST)
    packaged = _tree_hashes(PACKAGE_STATIC)
    if source != packaged:
        missing = sorted(set(source) - set(packaged))
        extra = sorted(set(packaged) - set(source))
        changed = sorted(key for key in set(source) & set(packaged) if source[key] != packaged[key])
        for line in (
            [f"missing in packaged static: {name}" for name in missing]
            + [f"stale extra in packaged static: {name}" for name in extra]
            + [f"content drift: {name}" for name in changed]
        ):
            print(line, file=sys.stderr)
        print("run scripts/sync_frontend_dist.py to resync", file=sys.stderr)
        return 1
    print(f"packaged static matches frontend/dist ({len(source)} files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
