"""FastAPI application factory for worktree-review-server."""

from __future__ import annotations

import os

from worktree_review import __version__
from worktree_review.observability import configure_logging

try:
    from fastapi import FastAPI, Request, Response, status
    from fastapi.responses import JSONResponse
except ImportError as exc:  # pragma: no cover - exercised only without the extra
    raise ImportError(
        "worktree_review.server.app requires the server extra: "
        "pip install 'worktree-review[server]'"
    ) from exc

from worktree_review.platform.github.retry import (
    GitHubRetryCoordinator,
    RetryAuthorizationError,
)
from worktree_review.platform.github.webhooks import (
    WebhookConfigurationError,
    WebhookValidationError,
    handle_github_webhook,
)
from worktree_review.server.state import StateConflictError


def create_app(
    *,
    github_webhook_secret: str | None = None,
    retry_coordinator: GitHubRetryCoordinator | None = None,
) -> FastAPI:
    configure_logging(json_output=True)
    configured_webhook_secret = github_webhook_secret or os.environ.get(
        "WORKTREE_REVIEW_GITHUB_WEBHOOK_SECRET"
    )
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
        if not configured_webhook_secret:
            return Response(status_code=status.HTTP_501_NOT_IMPLEMENTED)
        try:
            dispatch = await handle_github_webhook(
                payload=await request.body(),
                signature_header=request.headers.get("x-hub-signature-256"),
                webhook_secret=configured_webhook_secret,
                event_name=request.headers.get("x-github-event"),
                delivery_id=request.headers.get("x-github-delivery"),
                retry_coordinator=retry_coordinator,
            )
        except WebhookValidationError as exc:
            return Response(content=str(exc), status_code=status.HTTP_401_UNAUTHORIZED)
        except RetryAuthorizationError as exc:
            return Response(content=str(exc), status_code=status.HTTP_403_FORBIDDEN)
        except StateConflictError as exc:
            return Response(content=str(exc), status_code=status.HTTP_409_CONFLICT)
        except WebhookConfigurationError as exc:
            return Response(content=str(exc), status_code=status.HTTP_501_NOT_IMPLEMENTED)
        return JSONResponse(
            content=dispatch.model_dump(mode="json"),
            status_code=status.HTTP_202_ACCEPTED,
        )

    return application


app = create_app()
