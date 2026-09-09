"""FastAPI application factory for worktree-review-server."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

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
from worktree_review.platform.github.runtime import (
    ServerRuntime,
    ServerRuntimeBuilder,
    build_server_runtime_from_environment,
)
from worktree_review.platform.github.webhooks import (
    WebhookConfigurationError,
    WebhookValidationError,
    handle_github_webhook,
)
from worktree_review.platform.web.api import create_api_router
from worktree_review.platform.web.errors import ApiError
from worktree_review.platform.web.runtime import WebRuntime, open_web_runtime
from worktree_review.server.state import StateConflictError


def default_web_database_path() -> Path:
    override = os.environ.get("WORKTREE_REVIEW_WEB_DATABASE")
    if override:
        return Path(override)
    xdg = os.environ.get("XDG_STATE_HOME")
    if xdg:
        root = Path(xdg) / "worktree-review"
    else:
        root = Path.home() / ".local" / "state" / "worktree-review"
    return root / "web.sqlite"


def create_app(
    *,
    github_webhook_secret: str | None = None,
    retry_coordinator: GitHubRetryCoordinator | None = None,
    runtime_builder: ServerRuntimeBuilder | None = None,
    web_runtime: WebRuntime | None = None,
    enable_local_web: bool = True,
) -> FastAPI:
    configure_logging(json_output=True)
    configured_webhook_secret = github_webhook_secret or os.environ.get(
        "WORKTREE_REVIEW_GITHUB_WEBHOOK_SECRET"
    )

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        runtime: ServerRuntime | None = None
        opened_web: WebRuntime | None = None
        if retry_coordinator is not None:
            application.state.retry_coordinator = retry_coordinator
        elif configured_webhook_secret:
            builder = runtime_builder or build_server_runtime_from_environment
            runtime = await builder()
            application.state.retry_coordinator = runtime.retry_coordinator
        else:
            application.state.retry_coordinator = None
            application.state.retry_disabled_reason = (
                "WORKTREE_REVIEW_GITHUB_WEBHOOK_SECRET is not configured"
            )
        if web_runtime is not None:
            application.state.web_runtime = web_runtime
        elif enable_local_web:
            opened_web = await open_web_runtime(default_web_database_path())
            application.state.web_runtime = opened_web
        try:
            yield
        finally:
            if runtime is not None:
                await runtime.aclose()
            if opened_web is not None and opened_web.worker_task is not None:
                opened_web.worker_task.cancel()

    application = FastAPI(
        title="Worktree Review",
        version=__version__,
        summary="GitHub App webhook receiver and review workers.",
        lifespan=lifespan,
    )
    if web_runtime is not None:
        application.state.web_runtime = web_runtime

    @application.exception_handler(ApiError)
    async def api_error_handler(_request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.detail}},
        )

    application.include_router(create_api_router())

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
                retry_coordinator=getattr(
                    application.state,
                    "retry_coordinator",
                    retry_coordinator,
                ),
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
