"""FastAPI application factory for worktree-review-server."""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from worktree_review import __version__
from worktree_review.observability import configure_logging

try:
    from fastapi import FastAPI, Request, Response, status
    from fastapi.responses import FileResponse, JSONResponse
    from fastapi.staticfiles import StaticFiles
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
from worktree_review.platform.web.worker import execute_attempt, recover_interrupted
from worktree_review.server.state import StateConflictError

DEFAULT_BIND_HOST = "127.0.0.1"


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


def packaged_frontend_dist() -> Path:
    """Frontend bundle shipped inside the installed wheel (PM-101)."""
    return Path(__file__).resolve().parent / "static"


def default_frontend_dist() -> Path:
    override = os.environ.get("WORKTREE_REVIEW_FRONTEND_DIST")
    if override:
        return Path(override)
    packaged = packaged_frontend_dist()
    if (packaged / "index.html").is_file():
        return packaged
    return Path(__file__).resolve().parents[3] / "frontend" / "dist"


def require_frontend_dist(path: Path) -> Path:
    index = path / "index.html"
    if not index.is_file():
        raise RuntimeError(
            "frontend production build is missing at "
            f"{index}. Run `npm --prefix frontend run build` and "
            "`python scripts/sync_frontend_dist.py`, or set "
            "WORKTREE_REVIEW_FRONTEND_DIST; the local Web UI will not start "
            "with a blank page."
        )
    return path


def create_app(
    *,
    github_webhook_secret: str | None = None,
    retry_coordinator: GitHubRetryCoordinator | None = None,
    runtime_builder: ServerRuntimeBuilder | None = None,
    web_runtime: WebRuntime | None = None,
    enable_local_web: bool = True,
    start_worker: bool = True,
    start_github_worker: bool = True,
    serve_frontend: bool | None = None,
    frontend_dist: Path | None = None,
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
            application.state.trigger_coordinator = None
        elif configured_webhook_secret:
            builder = runtime_builder or build_server_runtime_from_environment
            runtime = await builder()
            application.state.server_runtime = runtime
            application.state.retry_coordinator = runtime.retry_coordinator
            application.state.trigger_coordinator = runtime.trigger_coordinator
            if (
                start_github_worker
                and runtime.durable_worker is not None
                and runtime.worker_task is None
            ):
                runtime.worker_task = asyncio.create_task(runtime.durable_worker.run_forever())
        else:
            application.state.retry_coordinator = None
            application.state.trigger_coordinator = None
            application.state.retry_disabled_reason = (
                "WORKTREE_REVIEW_GITHUB_WEBHOOK_SECRET is not configured"
            )
        if web_runtime is not None:
            application.state.web_runtime = web_runtime
        elif enable_local_web:
            opened_web = await open_web_runtime(default_web_database_path())
            application.state.web_runtime = opened_web
        local_web = getattr(application.state, "web_runtime", None)
        if isinstance(local_web, WebRuntime) and start_worker and enable_local_web:

            async def _execute(attempt_id: str) -> None:
                await execute_attempt(local_web, attempt_id)

            local_web.execute_attempt = _execute
            await recover_interrupted(local_web)
            local_web.worker_task = asyncio.create_task(local_web.run_worker())
        try:
            yield
        finally:
            if runtime is not None:
                await runtime.aclose()
            worker = getattr(application.state, "web_runtime", None)
            if isinstance(worker, WebRuntime) and worker.worker_task is not None:
                worker.worker_task.cancel()

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

    @application.middleware("http")
    async def authorized_deployment_gate(request: Request, call_next):  # type: ignore[no-untyped-def]
        """Authorized deployment mode: every remote API requires a verified
        session and is served no-store (P3 §4.1/§8). The default local mode
        (no authenticator) keeps its loopback process-level protections.

        Local SQLite admin routes and csrf-bootstrap are not part of the
        authorized surface: they answer uniform 404 without consulting
        client Host / Forwarded headers or revealing endpoint existence.
        """
        path = request.url.path
        if not path.startswith("/api/v1/"):
            return await call_next(request)
        server_runtime = getattr(request.app.state, "server_runtime", None)
        authenticator = getattr(server_runtime, "web_authenticator", None)
        if authenticator is None:
            return await call_next(request)

        def _local_admin_path(request_path: str, method: str) -> bool:
            if request_path == "/api/v1/csrf-bootstrap":
                return True
            for prefix in (
                "/api/v1/repositories",
                "/api/v1/provider-profiles",
                "/api/v1/review-policies",
                "/api/v1/compute-policies",
                "/api/v1/integrations/session-insight",
            ):
                if request_path == prefix or request_path.startswith(prefix + "/"):
                    return True
            if method == "POST" and request_path == "/api/v1/reviews":
                return True
            if (
                method == "POST"
                and request_path.startswith("/api/v1/reviews/")
                and request_path.endswith("/retry")
            ):
                return True
            return False

        if _local_admin_path(path, request.method):
            return JSONResponse(
                status_code=404,
                content={"error": {"code": "not_found", "message": "not found"}},
                headers={"Cache-Control": "no-store"},
            )
        if path.startswith("/api/v1/auth/"):
            return await call_next(request)
        if authenticator.session_for_cookie(request.headers.get("cookie")) is None:
            return JSONResponse(
                status_code=401,
                content={
                    "error": {
                        "code": "authentication_required",
                        "message": "a verified GitHub session is required",
                    }
                },
                headers={"Cache-Control": "no-store"},
            )
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    @application.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @application.post("/webhooks/github")
    async def github_webhook(request: Request) -> Response:
        if not configured_webhook_secret:
            return Response(status_code=status.HTTP_501_NOT_IMPLEMENTED)
        server_runtime = getattr(application.state, "server_runtime", None)
        web_authenticator = None if server_runtime is None else server_runtime.web_authenticator
        session_revoker = (
            None if web_authenticator is None else web_authenticator.revoke_actor_sessions
        )
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
                trigger_coordinator=getattr(application.state, "trigger_coordinator", None),
                session_revoker=session_revoker,
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

    should_serve = enable_local_web if serve_frontend is None else serve_frontend
    if should_serve:
        dist = require_frontend_dist(frontend_dist or default_frontend_dist())
        index_file = dist / "index.html"
        assets_dir = dist / "assets"
        if assets_dir.is_dir():
            application.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

        @application.get("/")
        async def frontend_index() -> FileResponse:
            return FileResponse(index_file)

        favicon = dist / "favicon.svg"
        if favicon.is_file():

            @application.get("/favicon.svg")
            async def frontend_favicon() -> FileResponse:
                return FileResponse(favicon)

        @application.get("/{full_path:path}")
        async def frontend_spa(full_path: str) -> FileResponse:
            if full_path.startswith(("api/", "webhooks/")) or full_path == "healthz":
                raise ApiError(404, "not_found", "not found")
            return FileResponse(index_file)

    return application


app = create_app()
