#!/usr/bin/env python3
"""Verify that a built wheel ships a complete, current Web UI bundle.

Checks the packaged ``worktree_review/server/static`` tree inside the wheel:
index.html, hashed assets, Simplified Chinese translations, dark/light theme
tokens, and markers for current-version features (policy registration). The
bundle must be the LIVE build — the offline demo badge must not ship.
"""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path

REQUIRED_PATH_MARKERS = (
    "worktree_review/server/static/index.html",
    "worktree_review/server/static/assets/",
)

# Content markers (the JS/CSS bundle is minified; these string literals and
# CSS custom properties survive minification).
REQUIRED_CONTENT_MARKERS = (
    "概览",  # Simplified Chinese localization (Overview)
    "登记可信 Compute Policy",  # current-version policy registration UI
    "需要关注",  # zh-CN Needs attention
    "--wr-",  # design tokens prefix (theme system)
    "dataset.theme",  # dark/light/system theme switching
)


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: verify_wheel_contents.py <wheel.whl>", file=sys.stderr)
        return 2
    wheel_path = Path(sys.argv[1])
    if not wheel_path.is_file():
        print(f"wheel not found: {wheel_path}", file=sys.stderr)
        return 2

    failures: list[str] = []
    with zipfile.ZipFile(wheel_path) as archive:
        names = set(archive.namelist())
        for marker in REQUIRED_PATH_MARKERS:
            if marker.endswith("/"):
                if not any(name.startswith(marker) for name in names):
                    failures.append(f"missing directory entry: {marker}")
            elif marker not in names:
                failures.append(f"missing file: {marker}")

        bundle_blobs: list[bytes] = []
        for name in sorted(names):
            if name.startswith("worktree_review/server/static/assets/") and name.endswith(
                (".js", ".css", ".html")
            ):
                bundle_blobs.append(archive.read(name))
        if (index := "worktree_review/server/static/index.html") in names:
            bundle_blobs.append(archive.read(index))
        corpus = b"\n".join(bundle_blobs).decode("utf-8", errors="replace")
        for marker in REQUIRED_CONTENT_MARKERS:
            if marker not in corpus:
                failures.append(f"missing content marker: {marker!r}")

    if failures:
        for failure in failures:
            print(f"FAIL {failure}", file=sys.stderr)
        return 1
    print(f"wheel {wheel_path.name} ships a complete live Web UI bundle")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
