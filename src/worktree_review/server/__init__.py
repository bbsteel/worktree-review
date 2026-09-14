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

    import os

    from worktree_review.server.app import DEFAULT_BIND_HOST

    uvicorn.run(
        "worktree_review.server.app:app",
        host=os.environ.get("WORKTREE_REVIEW_BIND_HOST", DEFAULT_BIND_HOST),
        port=int(os.environ.get("WORKTREE_REVIEW_BIND_PORT", "8000")),
        factory=False,
    )
