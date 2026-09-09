"""HTTP API for local Web. Pipeline does not run inside the request."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Header, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from worktree_review.application.lifecycle import RunStatus
from worktree_review.application.review_events import ReviewEvent
from worktree_review.application.review_service import allocate_attempt_id
from worktree_review.core.git import invoke_git, worktree_is_clean
from worktree_review.core.policy import load_compute_policy, load_review_policy
from worktree_review.platform.web.errors import ApiError
from worktree_review.platform.web.local_store import IdempotencyConflictError
from worktree_review.platform.web.presenters import (
    present_compute_policy,
    present_overview,
    present_provider_profile,
    present_repository,
    present_review_policy,
    present_review_run,
    present_review_summary,
    repository_display_name,
)
from worktree_review.platform.web.registry import (
    TrustBoundaryError,
    parse_credential_reference,
    register_local_repository,
    require_registered_repository_path,
    resolve_credential_reference,
)
from worktree_review.platform.web.runtime import WebRuntime
from worktree_review.platform.web.security import assert_local_mutation_headers
from worktree_review.platform.web.sse import iter_attempt_events


class LocalWorktreeSource(BaseModel):
    kind: Literal["local-worktree"]
    target_ref: str | None = None


class LocalRecentCommitsSource(BaseModel):
    kind: Literal["local-recent-commits"]
    commit_count: int = Field(ge=0)


class LocalCommittedRefSource(BaseModel):
    kind: Literal["local-committed-ref"]
    proposed_ref: str
    target_ref: str | None = None


class CreateReviewRequest(BaseModel):
    repository_id: str
    source: Annotated[
        LocalWorktreeSource | LocalRecentCommitsSource | LocalCommittedRefSource,
        Field(discriminator="kind"),
    ]
    review_policy_id: str
    compute_policy_id: str


class RegisterRepositoryRequest(BaseModel):
    path: str
    display_name: str | None = None


class SaveProviderProfileRequest(BaseModel):
    name: str
    provider: str
    endpoint: str | None = None
    credential_reference: str | None = None
    local_cli_adapter: str | None = None
    local_cli_command: list[str] | None = None
    adapter_label: str | None = None


def _runtime(request: Request) -> WebRuntime:
    runtime = request.app.state.web_runtime
    if not isinstance(runtime, WebRuntime):
        raise ApiError(500, "web_runtime_missing", "local web runtime is not configured")
    return runtime


def _mutation_guard(request: Request, csrf_token: str | None) -> None:
    assert_local_mutation_headers(
        request.headers.get("host"),
        request.headers.get("origin"),
        csrf_token,
    )


async def _load_policies(runtime: WebRuntime, request_body: dict[str, Any]) -> tuple[Any, Any]:
    review_row = await runtime.store.get_trusted_policy(
        "trusted_review_policies", str(request_body.get("review_policy_id") or "")
    )
    compute_row = await runtime.store.get_trusted_policy(
        "trusted_compute_policies", str(request_body.get("compute_policy_id") or "")
    )
    review_policy = load_review_policy(Path(review_row["path"]))[0] if review_row else None
    compute_policy = load_compute_policy(Path(compute_row["path"]))[0] if compute_row else None
    return review_policy, compute_policy


def create_api_router() -> APIRouter:
    router = APIRouter()

    @router.post("/api/v1/reviews", status_code=202)
    async def create_review(
        payload: CreateReviewRequest,
        request: Request,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
    ) -> dict[str, str]:
        runtime = _runtime(request)
        _mutation_guard(request, csrf_token)
        if not idempotency_key:
            raise ApiError(400, "missing_idempotency_key", "Idempotency-Key is required")
        repository = await runtime.store.get_repository(payload.repository_id)
        if repository is None:
            raise ApiError(404, "repository_not_found", "unknown repository_id")
        try:
            await require_registered_repository_path(
                runtime.store, Path(repository["canonical_root"])
            )
        except TrustBoundaryError as exc:
            raise ApiError(403, "unregistered_repository", str(exc)) from exc
        review_row = await runtime.store.get_trusted_policy(
            "trusted_review_policies", payload.review_policy_id
        )
        compute_row = await runtime.store.get_trusted_policy(
            "trusted_compute_policies", payload.compute_policy_id
        )
        if review_row is None:
            raise ApiError(404, "review_policy_not_found", "unknown review_policy_id")
        if compute_row is None:
            raise ApiError(404, "compute_policy_not_found", "unknown compute_policy_id")
        request_json = payload.model_dump_json()
        digest = hashlib.sha256(request_json.encode("utf-8")).hexdigest()
        attempt_id = allocate_attempt_id()
        event = ReviewEvent(
            sequence=1,
            occurred_at=datetime.now(UTC),
            attempt_id=attempt_id,
            surface="web",
            event_type="attempt.created",
            payload={
                "source": payload.source.kind,
                "repository_id": payload.repository_id,
                "repository_display": repository["display_name"],
            },
        )
        try:
            stored_id = await runtime.store.create_attempt_with_initial_event_and_idempotency(
                attempt_id=attempt_id,
                idempotency_key=idempotency_key,
                request_digest=digest,
                initial_event=event,
                run_status=RunStatus.QUEUED,
                request_json=request_json,
            )
        except IdempotencyConflictError as exc:
            raise ApiError(409, "idempotency_conflict", str(exc)) from exc
        if stored_id == attempt_id:
            await runtime.enqueue(stored_id)
        return {"attempt_id": stored_id}

    @router.get("/api/v1/reviews")
    async def list_reviews(request: Request) -> dict[str, Any]:
        runtime = _runtime(request)
        runs = await runtime.store.list_runs()
        summaries: list[dict[str, Any]] = []
        for run in runs:
            request_body = json.loads(run.request_json) if run.request_json else {}
            display = await repository_display_name(runtime.store, request_body)
            summaries.append(present_review_summary(run, display_name=display))
        return {"runs": summaries, "next_cursor": None}

    @router.get("/api/v1/reviews/{attempt_id}")
    async def get_review(attempt_id: str, request: Request) -> dict[str, Any]:
        runtime = _runtime(request)
        run = await runtime.store.get_run(attempt_id)
        if run is None:
            raise ApiError(404, "attempt_not_found", "unknown attempt")
        request_body = json.loads(run.request_json) if run.request_json else {}
        display = await repository_display_name(runtime.store, request_body)
        review_policy, compute_policy = await _load_policies(runtime, request_body)
        return present_review_run(
            run,
            display_name=display,
            review_policy=review_policy,
            compute_policy=compute_policy,
        )

    @router.get("/api/v1/reviews/{attempt_id}/events")
    async def review_events(
        attempt_id: str,
        request: Request,
        last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
        since: int | None = None,
    ) -> StreamingResponse:
        runtime = _runtime(request)
        run = await runtime.store.get_run(attempt_id)
        if run is None:
            raise ApiError(404, "attempt_not_found", "unknown attempt")

        async def _stream() -> Any:
            async for item in iter_attempt_events(
                runtime, attempt_id, last_event_id=last_event_id, since=since
            ):
                if item is None:
                    yield ": heartbeat\n\n"
                    continue
                yield f"id: {item.sequence}\ndata: {item.model_dump_json(by_alias=True)}\n\n"

        return StreamingResponse(_stream(), media_type="text/event-stream")

    @router.get("/api/v1/reviews/{attempt_id}/result")
    async def get_review_result(attempt_id: str, request: Request) -> Any:
        runtime = _runtime(request)
        run = await runtime.store.get_run(attempt_id)
        if run is None:
            raise ApiError(404, "attempt_not_found", "unknown attempt")
        if not run.result_json:
            raise ApiError(409, "result_unavailable", "terminal result is not available yet")
        return json.loads(run.result_json)

    @router.post("/api/v1/reviews/{attempt_id}/retry", status_code=202)
    async def retry_review(
        attempt_id: str,
        request: Request,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
    ) -> dict[str, str]:
        runtime = _runtime(request)
        _mutation_guard(request, csrf_token)
        if not idempotency_key:
            raise ApiError(400, "missing_idempotency_key", "Idempotency-Key is required")
        original = await runtime.store.get_run(attempt_id)
        if original is None or not original.request_json:
            raise ApiError(404, "attempt_not_found", "unknown attempt")
        digest = hashlib.sha256(f"retry:{attempt_id}:{original.request_json}".encode()).hexdigest()
        new_id = allocate_attempt_id()
        event = ReviewEvent(
            sequence=1,
            occurred_at=datetime.now(UTC),
            attempt_id=new_id,
            surface="web",
            event_type="attempt.created",
            payload={"retry_of": attempt_id, "source": "retry"},
        )
        try:
            stored_id = await runtime.store.create_attempt_with_initial_event_and_idempotency(
                attempt_id=new_id,
                idempotency_key=idempotency_key,
                request_digest=digest,
                initial_event=event,
                run_status=RunStatus.QUEUED,
                request_json=original.request_json,
            )
        except IdempotencyConflictError as exc:
            raise ApiError(409, "idempotency_conflict", str(exc)) from exc
        if stored_id == new_id:
            await runtime.enqueue(stored_id)
        return {"attempt_id": stored_id}

    @router.get("/api/v1/overview")
    async def overview(request: Request) -> dict[str, Any]:
        runtime = _runtime(request)
        aggregate = await runtime.store.overview_aggregate()
        runs = await runtime.store.list_runs()
        summaries: list[dict[str, Any]] = []
        for run in runs:
            request_body = json.loads(run.request_json) if run.request_json else {}
            display = await repository_display_name(runtime.store, request_body)
            summaries.append(present_review_summary(run, display_name=display))
        return present_overview(aggregate, summaries)

    @router.get("/api/v1/repositories")
    async def list_repositories(request: Request) -> list[dict[str, Any]]:
        runtime = _runtime(request)
        return [present_repository(row) for row in await runtime.store.list_repositories()]

    @router.post("/api/v1/repositories", status_code=201)
    async def create_repository(
        payload: RegisterRepositoryRequest,
        request: Request,
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
    ) -> dict[str, Any]:
        runtime = _runtime(request)
        _mutation_guard(request, csrf_token)
        try:
            row = await register_local_repository(
                runtime.store,
                requested_root=Path(payload.path),
                display_name=payload.display_name or payload.path,
            )
        except TrustBoundaryError as exc:
            raise ApiError(400, "invalid_repository", str(exc)) from exc
        return present_repository(row)

    @router.get("/api/v1/repositories/{repository_id}/status")
    async def repository_status(repository_id: str, request: Request) -> dict[str, Any]:
        runtime = _runtime(request)
        row = await runtime.store.get_repository(repository_id)
        if row is None:
            raise ApiError(404, "repository_not_found", "unknown repository")
        root = Path(row["canonical_root"])
        branch = (await invoke_git("rev-parse", "--abbrev-ref", "HEAD", cwd=root)).stdout.strip()
        head_oid = (await invoke_git("rev-parse", "HEAD", cwd=root)).stdout.strip()
        porcelain = (await invoke_git("status", "--porcelain", cwd=root)).stdout.splitlines()
        tracked = sum(1 for line in porcelain if line and not line.startswith("??"))
        untracked = sum(1 for line in porcelain if line.startswith("??"))
        return {
            "repository_id": repository_id,
            "branch": branch,
            "head_oid": head_oid,
            "dirty": not await worktree_is_clean(root),
            "tracked_modifications": tracked,
            "untracked_files": untracked,
            "accessible": True,
            "identity_drift": False,
        }

    @router.delete("/api/v1/repositories/{repository_id}", status_code=204)
    async def delete_repository(
        repository_id: str,
        request: Request,
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
    ) -> None:
        runtime = _runtime(request)
        _mutation_guard(request, csrf_token)
        deleted = await runtime.store.delete_repository(repository_id)
        if not deleted:
            raise ApiError(404, "repository_not_found", "unknown repository")

    @router.get("/api/v1/provider-profiles")
    async def list_provider_profiles(request: Request) -> list[dict[str, Any]]:
        runtime = _runtime(request)
        return [
            present_provider_profile(row) for row in await runtime.store.list_provider_profiles()
        ]

    @router.post("/api/v1/provider-profiles", status_code=201)
    async def create_provider_profile(
        payload: SaveProviderProfileRequest,
        request: Request,
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
    ) -> dict[str, Any]:
        runtime = _runtime(request)
        _mutation_guard(request, csrf_token)
        if payload.credential_reference:
            try:
                parse_credential_reference(payload.credential_reference)
            except TrustBoundaryError as exc:
                raise ApiError(400, "invalid_credential_reference", str(exc)) from exc
        profile_id = str(uuid.uuid4())
        await runtime.store.insert_provider_profile(
            profile_id=profile_id,
            name=payload.name,
            provider=payload.provider,
            credential_reference=payload.credential_reference,
            endpoint=payload.endpoint,
        )
        row = await runtime.store.get_provider_profile(profile_id)
        assert row is not None
        return present_provider_profile(row)

    @router.patch("/api/v1/provider-profiles/{profile_id}")
    async def update_provider_profile(
        profile_id: str,
        payload: SaveProviderProfileRequest,
        request: Request,
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
    ) -> dict[str, Any]:
        runtime = _runtime(request)
        _mutation_guard(request, csrf_token)
        existing = await runtime.store.get_provider_profile(profile_id)
        if existing is None:
            raise ApiError(404, "provider_profile_not_found", "unknown provider profile")
        if payload.credential_reference:
            try:
                parse_credential_reference(payload.credential_reference)
            except TrustBoundaryError as exc:
                raise ApiError(400, "invalid_credential_reference", str(exc)) from exc
        await runtime.store.update_provider_profile(
            profile_id=profile_id,
            name=payload.name,
            provider=payload.provider,
            credential_reference=payload.credential_reference,
            endpoint=payload.endpoint,
        )
        row = await runtime.store.get_provider_profile(profile_id)
        assert row is not None
        return present_provider_profile(row)

    @router.delete("/api/v1/provider-profiles/{profile_id}", status_code=204)
    async def delete_provider_profile(
        profile_id: str,
        request: Request,
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
    ) -> None:
        runtime = _runtime(request)
        _mutation_guard(request, csrf_token)
        deleted = await runtime.store.delete_provider_profile(profile_id)
        if not deleted:
            raise ApiError(404, "provider_profile_not_found", "unknown provider profile")

    @router.post("/api/v1/provider-profiles/{profile_id}/test")
    async def test_provider_profile(
        profile_id: str,
        request: Request,
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
    ) -> dict[str, Any]:
        runtime = _runtime(request)
        _mutation_guard(request, csrf_token)
        row = await runtime.store.get_provider_profile(profile_id)
        if row is None:
            raise ApiError(404, "provider_profile_not_found", "unknown provider profile")
        observed_at = datetime.now(UTC).isoformat()
        reference = row.get("credential_reference")
        if not reference:
            return {
                "ok": False,
                "detail": "credential reference is not configured",
                "tested_at": observed_at,
            }
        try:
            resolve_credential_reference(reference)
        except TrustBoundaryError as exc:
            return {"ok": False, "detail": str(exc), "tested_at": observed_at}
        return {"ok": True, "detail": "credential reference resolved", "tested_at": observed_at}

    @router.get("/api/v1/review-policies")
    async def list_review_policies(request: Request) -> list[dict[str, Any]]:
        runtime = _runtime(request)
        items = []
        for row in await runtime.store.list_trusted_policies("trusted_review_policies"):
            policy = load_review_policy(Path(row["path"]))[0]
            items.append(present_review_policy(row, policy))
        return items

    @router.get("/api/v1/review-policies/{policy_id}")
    async def get_review_policy(policy_id: str, request: Request) -> dict[str, Any]:
        runtime = _runtime(request)
        row = await runtime.store.get_trusted_policy("trusted_review_policies", policy_id)
        if row is None:
            raise ApiError(404, "review_policy_not_found", "unknown review policy")
        policy = load_review_policy(Path(row["path"]))[0]
        return present_review_policy(row, policy)

    @router.get("/api/v1/compute-policies")
    async def list_compute_policies(request: Request) -> list[dict[str, Any]]:
        runtime = _runtime(request)
        items = []
        for row in await runtime.store.list_trusted_policies("trusted_compute_policies"):
            policy = load_compute_policy(Path(row["path"]))[0]
            items.append(present_compute_policy(row, policy))
        return items

    @router.get("/api/v1/compute-policies/{policy_id}")
    async def get_compute_policy(policy_id: str, request: Request) -> dict[str, Any]:
        runtime = _runtime(request)
        row = await runtime.store.get_trusted_policy("trusted_compute_policies", policy_id)
        if row is None:
            raise ApiError(404, "compute_policy_not_found", "unknown compute policy")
        policy = load_compute_policy(Path(row["path"]))[0]
        return present_compute_policy(row, policy)

    return router
