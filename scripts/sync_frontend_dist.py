#!/usr/bin/env python3
"""Copy the frontend production build into the Python package (PM-101).

Builds nothing itself — run `npm --prefix frontend run build` first. The
copy lands at src/worktree_review/server/static/, which hatch ships in the
wheel/sdist via the `artifacts` table, so an installed
`worktree-review[server]` process can serve the Web UI without a source
checkout. The directory is gitignored: it is a build artifact, regenerated
at packaging time.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIST = REPO_ROOT / "frontend" / "dist"
PACKAGE_STATIC = REPO_ROOT / "src" / "worktree_review" / "server" / "static"


def main() -> int:
    index = SOURCE_DIST / "index.html"
    if not index.is_file():
        print(
            f"frontend build missing at {index}; run `npm --prefix frontend run build` first",
            file=sys.stderr,
        )
        return 1
    if PACKAGE_STATIC.exists():
        shutil.rmtree(PACKAGE_STATIC)
    shutil.copytree(SOURCE_DIST, PACKAGE_STATIC)
    print(f"synced {SOURCE_DIST} -> {PACKAGE_STATIC}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
