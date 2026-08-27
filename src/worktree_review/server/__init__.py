"""``worktree-review-server`` GitHub App process: webhook HTTP + embedded workers (D8, D12)."""

from __future__ import annotations


def main() -> None:
    """Console entry point. Requires the ``worktree-review[server]`` extra."""

    try:
        import uvicorn
    except ImportError as exc:
        raise SystemExit(
            "worktree-review-server requires the server extra: "
            "pip install 'worktree-review[server]'"
        ) from exc

    uvicorn.run(
        "worktree_review.server.app:app",
        host="0.0.0.0",
        port=8000,
        factory=False,
    )
