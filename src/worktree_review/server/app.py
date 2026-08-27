"""FastAPI application factory for worktree-review-server."""

from __future__ import annotations

from worktree_review import __version__
from worktree_review.observability import configure_logging

try:
    from fastapi import FastAPI, Request, Response, status
except ImportError as exc:  # pragma: no cover - exercised only without the extra
    raise ImportError(
        "worktree_review.server.app requires the server extra: "
        "pip install 'worktree-review[server]'"
    ) from exc


def create_app() -> FastAPI:
    configure_logging(json_output=True)
    application = FastAPI(
        title="Worktree Review",
        version=__version__,
        summary="GitHub App webhook receiver and review workers.",
    )

    @application.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @application.post("/webhooks/github")
    async def github_webhook(request: Request) -> Response:
        # Signature validation, identity invalidation, and enqueue land with the App.
        await request.body()
        return Response(status_code=status.HTTP_501_NOT_IMPLEMENTED)

    return application


app = create_app()
