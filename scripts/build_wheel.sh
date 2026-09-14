#!/usr/bin/env bash
# Reproducible packaging pipeline: frontend build → static sync → drift check → wheel/sdist.
#
# The packaged Web UI is the LIVE build (the default). The offline demo bundle
# (npm run build:demo) is never synced into the wheel.
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> building frontend (live production bundle)"
npm --prefix frontend ci
npm --prefix frontend run build

echo "==> syncing frontend/dist into the Python package"
python3 scripts/sync_frontend_dist.py

echo "==> verifying no drift between dist and packaged static"
python3 scripts/check_frontend_static_drift.py

echo "==> building wheel and sdist"
uv build

WHEEL=$(ls -t dist/worktree_review-*-py3-none-any.whl | head -1)
echo "==> verifying $WHEEL contains the current Web UI bundle"
python3 scripts/verify_wheel_contents.py "$WHEEL"

echo "==> packaging pipeline complete"
