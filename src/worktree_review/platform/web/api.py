"""HTTP API for local Web. Pipeline does not run inside the request."""

from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from worktree_review.application.lifecycle import RunStatus
from worktree_review.application.review_events import ReviewEvent
from worktree_review.application.review_runs import OverviewAggregate
from worktree_review.application.review_service import allocate_attempt_id
from worktree_review.core.errors import InvalidInvocationError
from worktree_review.core.git import invoke_git, worktree_is_clean
from worktree_review.core.policy import load_review_policy
from worktree_review.platform.github.runtime import ServerRuntime
from worktree_review.platform.web.errors import ApiError
from worktree_review.platform.web.local_store import IdempotencyConflictError
from worktree_review.platform.web.presenters import (
    present_compute_policy,
    present_github_review_run,
    present_overview,
    present_provider_profile,
    present_repository,
    present_review_policy,
    present_review_run,
    present_review_summary,
    repository_display_name,
)
from worktree_review.platform.web.provider_resolution import freeze_provider_profile
from worktree_review.platform.web.registry import (
    TrustBoundaryError,
    load_trusted_compute_document,
    parse_credential_reference,
    profile_command_argv,
    register_local_repository,
    register_trusted_policy,
    require_registered_repository_path,
    resolve_credential_reference,
    validate_compute_policy_binding,
    validate_provider_profile_shape,
)
from worktree_review.platform.web.runtime import WebRuntime
from worktree_review.platform.web.security import assert_local_mutation_headers, is_loopback_host
from worktree_review.platform.web.sse import iter_attempt_events, iter_github_attempt_events
from worktree_review.server.state import JobStatus as GitHubJobStatus


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


class RegisterReviewPolicyRequest(BaseModel):
    path: str


class RegisterComputePolicyRequest(BaseModel):
    path: str
    provider_profile_id: str | None = None


def _runtime(request: Request) -> WebRuntime:
    runtime = request.app.state.web_runtime
    if not isinstance(runtime, WebRuntime):
        raise ApiError(500, "web_runtime_missing", "local web runtime is not configured")
    return runtime


def _web_runtime(request: Request) -> WebRuntime | None:
    runtime = getattr(request.app.state, "web_runtime", None)
    return runtime if isinstance(runtime, WebRuntime) else None


def _server_runtime(request: Request) -> ServerRuntime | None:
    runtime = getattr(request.app.state, "server_runtime", None)
    return runtime if isinstance(runtime, ServerRuntime) else None


async def _github_review_dto(
    request: Request,
    attempt_id: str,
    *,
    session_insight_state: str = "disconnected",
    session_insight_deep_link: str | None = None,
) -> dict[str, Any] | None:
    server = _server_runtime(request)
    if server is None or server.github_store is None or server.attempt_store is None:
        return None
    snapshot = await server.github_store.get_execution_snapshot(attempt_id)
    if snapshot is None:
        return None
    change_state = await server.attempt_store.get_change_request_state(snapshot.change_request)
    publication_status = await server.github_store.publication_status(attempt_id)
    check_run_id = await server.github_store.get_check_run_id(attempt_id)
    result_json = await server.github_store.get_review_result(attempt_id)
    created_at = await server.github_store.get_attempt_created_at(attempt_id)
    if created_at is None:
        events = await server.github_store.list_review_events(attempt_id)
        created_at = events[0].occurred_at if events else datetime.fromtimestamp(0, tz=UTC)
    job_status_value = await server.attempt_store.job_status(attempt_id)
    return present_github_review_run(
        snapshot=snapshot,
        change_state=change_state,
        publication_status=publication_status,
        check_run_id=check_run_id,
        result_json=result_json,
        created_at=created_at,
        session_insight_state=session_insight_state,
        session_insight_deep_link=session_insight_deep_link,
        job_status=None if job_status_value is None else job_status_value.value,
        job_failure_detail=await server.attempt_store.job_last_error(attempt_id),
    )


def _mutation_guard(request: Request, csrf_token: str | None) -> None:
    runtime = _runtime(request)
    assert_local_mutation_headers(
        request.headers.get("host"),
        request.headers.get("origin"),
        csrf_token,
        expected_csrf_token=runtime.csrf_token,
    )


async def _session_insight_projection(
    runtime: WebRuntime,
) -> tuple[str, str | None, dict[str, Any]]:
    """Probe Session Insight once and derive (state, deep-link base, overview block)."""
    probe = await runtime.session_insight.current()
    state = probe.state.value
    block: dict[str, Any] = {
        "state": state,
        "base_url": probe.base_url,
        "current_attempt_id": None,
        "child_session_count": 0,
        "last_probe_at": probe.probed_at,
        "detail": probe.detail,
        "reader_revision": probe.reader_revision,
        "journal": {
            "enabled": runtime.journal is not None,
            "ok": runtime.journal is not None and runtime.journal.last_error is None,
            "last_error": None if runtime.journal is None else runtime.journal.last_error,
            "last_error_at": None if runtime.journal is None else runtime.journal.last_error_at,
        },
    }
    deep_link_base = probe.base_url if probe.state.value == "connected" else None
    return state, deep_link_base, block


async def _merged_overview_aggregate(
    request: Request, local_aggregate: OverviewAggregate
) -> OverviewAggregate:
    """Stats must not silently exclude GitHub Attempts — including queued,
    running and failed-without-result ones (reviewer blocker 3)."""
    server = _server_runtime(request)
    if server is None or server.github_store is None or server.attempt_store is None:
        return local_aggregate
    gate_counts = await server.github_store.overview_gate_counts()
    job_counts = await server.attempt_store.job_status_counts()
    github_total = sum(job_counts.values())
    if github_total == 0:
        return local_aggregate
    # Only a failed job WITHOUT a saved result counts as an error: an attempt
    # that produced a Passed/Blocked result but exhausted publication retries
    # keeps its gate — a publication failure never rewrites the Core Gate.
    github_failed_without_result = 0
    for failed_attempt_id in await server.attempt_store.job_ids_with_status(GitHubJobStatus.FAILED):
        if await server.github_store.get_review_result(failed_attempt_id) is None:
            github_failed_without_result += 1
    return OverviewAggregate(
        attempt_count=local_aggregate.attempt_count + github_total,
        passed_count=local_aggregate.passed_count + gate_counts.get("Passed", 0),
        blocked_count=local_aggregate.blocked_count + gate_counts.get("Blocked", 0),
        error_count=(
            local_aggregate.error_count + gate_counts.get("Error", 0) + github_failed_without_result
        ),
        known_cost_usd=local_aggregate.known_cost_usd,
        # GitHub results do not report measured cost yet; count them honestly.
        unknown_cost_record_count=local_aggregate.unknown_cost_record_count + github_total,
    )


async def _github_recent_summaries(request: Request) -> list[dict[str, Any]]:
    """Recent GitHub Attempts projected onto the Review Summary shape."""
    server = _server_runtime(request)
    if server is None or server.github_store is None or server.attempt_store is None:
        return []
    summaries: list[dict[str, Any]] = []
    for attempt_id in await server.github_store.list_recent_attempt_ids():
        dto = await _github_review_dto(request, attempt_id)
        if dto is not None:
            summaries.append(dto["summary"])
    return summaries


async def _load_policies(runtime: WebRuntime, request_body: dict[str, Any]) -> tuple[Any, Any]:
    review_row = await runtime.store.get_trusted_policy(
        "trusted_review_policies", str(request_body.get("review_policy_id") or "")
    )
    compute_row = await runtime.store.get_trusted_policy(
        "trusted_compute_policies", str(request_body.get("compute_policy_id") or "")
    )
    review_policy = load_review_policy(Path(review_row["path"]))[0] if review_row else None
    compute_policy = (
        load_trusted_compute_document(Path(compute_row["path"]))[0] if compute_row else None
    )
    return review_policy, compute_policy


async def _freeze_bound_provider(runtime: WebRuntime, compute_row: dict[str, Any]) -> str | None:
    """Resolve the Compute Policy's bound Provider Profile into a frozen snapshot.

    The snapshot freezes the profile reference and its non-secret
    configuration identity at Attempt creation; later profile edits never
    change a historical Attempt.
    """
    profile_id = compute_row.get("provider_profile_id")
    if not profile_id:
        raise ApiError(
            409,
            "compute_policy_unbound",
            "the Compute Policy is not bound to a Provider Profile; register it "
            "with provider_profile_id so reviews have a real compute connection",
        )
    profile_row = await runtime.store.get_provider_profile(str(profile_id))
    if profile_row is None:
        raise ApiError(
            409,
            "provider_profile_missing",
            "the Provider Profile bound to this Compute Policy no longer exists",
        )
    # The binding was validated at policy registration; re-validate now so a
    # profile edited in between cannot slip a different provider or command
    # under the trusted Compute Policy identity.
    compute_policy = load_trusted_compute_document(Path(compute_row["path"]))[0]
    try:
        validate_compute_policy_binding(compute_policy, profile_row)
    except TrustBoundaryError as exc:
        raise ApiError(409, "provider_profile_binding_drifted", str(exc)) from exc
    return freeze_provider_profile(profile_row)


def _policy_drifted(row: dict[str, Any], current_identity: Any) -> bool:
    """True when the trusted file on disk no longer matches the registered sha256."""
    registered_sha256 = row.get("version_sha256")
    return bool(registered_sha256) and registered_sha256 != current_identity.sha256


async def _bound_profile_name(runtime: WebRuntime, compute_row: dict[str, Any]) -> str | None:
    profile_id = compute_row.get("provider_profile_id")
    if not profile_id:
        return None
    profile = await runtime.store.get_provider_profile(str(profile_id))
    return None if profile is None else str(profile["name"])


def create_api_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/v1/csrf-bootstrap")
    async def csrf_bootstrap(request: Request) -> JSONResponse:
        """Issue this process's CSRF token to the same-origin frontend.

        Loopback-only and never cached; no CORS headers exist anywhere in
        this app, so a cross-origin page cannot read this response.
        """
        runtime = _runtime(request)
        if not is_loopback_host(request.headers.get("host")):
            raise ApiError(403, "forbidden_host", "CSRF bootstrap is only served on loopback")
        return JSONResponse(
            content={"csrf_token": runtime.csrf_token},
            headers={"Cache-Control": "no-store"},
        )

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
        frozen_provider_json = await _freeze_bound_provider(runtime, compute_row)
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
                frozen_provider_json=frozen_provider_json,
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
        summaries.extend(await _github_recent_summaries(request))
        summaries.sort(key=lambda item: str(item["created_at"]), reverse=True)
        return {"runs": summaries, "next_cursor": None}

    @router.get("/api/v1/reviews/{attempt_id}")
    async def get_review(attempt_id: str, request: Request) -> dict[str, Any]:
        runtime = _web_runtime(request)
        session_insight_state = "disconnected"
        session_insight_deep_link: str | None = None
        if runtime is not None:
            probe = await runtime.session_insight.current()
            session_insight_state = probe.state.value
            if session_insight_state == "connected":
                session_insight_deep_link = runtime.session_insight.deep_link(attempt_id)
            run = await runtime.store.get_run(attempt_id)
            if run is not None:
                request_body = json.loads(run.request_json) if run.request_json else {}
                display = await repository_display_name(runtime.store, request_body)
                review_policy, compute_policy = await _load_policies(runtime, request_body)
                return present_review_run(
                    run,
                    display_name=display,
                    review_policy=review_policy,
                    compute_policy=compute_policy,
                    session_insight_state=session_insight_state,
                    session_insight_deep_link=session_insight_deep_link,
                )
        github = await _github_review_dto(
            request,
            attempt_id,
            session_insight_state=session_insight_state,
            session_insight_deep_link=session_insight_deep_link,
        )
        if github is not None:
            return github
        raise ApiError(404, "attempt_not_found", "unknown attempt")

    @router.get("/api/v1/reviews/{attempt_id}/events")
    async def review_events(
        attempt_id: str,
        request: Request,
        last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
        since: int | None = None,
    ) -> StreamingResponse:
        runtime = _web_runtime(request)
        if runtime is not None:
            run = await runtime.store.get_run(attempt_id)
            if run is not None:

                async def _stream_local() -> Any:
                    async for item in iter_attempt_events(
                        runtime, attempt_id, last_event_id=last_event_id, since=since
                    ):
                        if item is None:
                            yield ": heartbeat\n\n"
                            continue
                        event_json = item.model_dump_json(by_alias=True)
                        yield f"id: {item.sequence}\ndata: {event_json}\n\n"

                return StreamingResponse(_stream_local(), media_type="text/event-stream")
        server = _server_runtime(request)
        if server is not None and server.github_store is not None:
            snapshot = await server.github_store.get_execution_snapshot(attempt_id)
            if snapshot is not None:
                github_store = server.github_store

                async def _stream_github() -> Any:
                    async for item in iter_github_attempt_events(
                        github_store, attempt_id, last_event_id=last_event_id, since=since
                    ):
                        if item is None:
                            yield ": heartbeat\n\n"
                            continue
                        event_json = item.model_dump_json(by_alias=True)
                        yield f"id: {item.sequence}\ndata: {event_json}\n\n"

                return StreamingResponse(_stream_github(), media_type="text/event-stream")
        raise ApiError(404, "attempt_not_found", "unknown attempt")

    @router.get("/api/v1/reviews/{attempt_id}/result")
    async def get_review_result(attempt_id: str, request: Request) -> Any:
        runtime = _web_runtime(request)
        if runtime is not None:
            run = await runtime.store.get_run(attempt_id)
            if run is not None:
                if not run.result_json:
                    raise ApiError(
                        409, "result_unavailable", "terminal result is not available yet"
                    )
                return json.loads(run.result_json)
        server = _server_runtime(request)
        if server is not None and server.github_store is not None:
            result_json = await server.github_store.get_review_result(attempt_id)
            if result_json:
                return json.loads(result_json)
            snapshot = await server.github_store.get_execution_snapshot(attempt_id)
            if snapshot is not None:
                raise ApiError(409, "result_unavailable", "terminal result is not available yet")
        raise ApiError(404, "attempt_not_found", "unknown attempt")

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
                frozen_provider_json=original.frozen_provider_json,
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
        summaries.extend(await _github_recent_summaries(request))
        summaries.sort(key=lambda item: str(item["created_at"]), reverse=True)
        _state_name, _deep_link_base, session_insight_block = await _session_insight_projection(
            runtime
        )
        aggregate = await _merged_overview_aggregate(request, aggregate)
        return present_overview(aggregate, summaries, session_insight=session_insight_block)

    @router.get("/api/v1/integrations/session-insight")
    async def session_insight_status(request: Request) -> dict[str, Any]:
        """Integration status probe. Advisory only; never a Gate input."""
        runtime = _runtime(request)
        _state_name, _deep_link_base, session_insight_block = await _session_insight_projection(
            runtime
        )
        return session_insight_block

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
        items = []
        for row in await runtime.store.list_provider_profiles():
            in_use = await runtime.store.provider_profile_in_use(str(row["id"]))
            items.append(present_provider_profile(row, referenced_by_history=in_use))
        return items

    @router.post("/api/v1/provider-profiles", status_code=201)
    async def create_provider_profile(
        payload: SaveProviderProfileRequest,
        request: Request,
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
    ) -> dict[str, Any]:
        runtime = _runtime(request)
        _mutation_guard(request, csrf_token)
        try:
            validate_provider_profile_shape(
                provider=payload.provider,
                endpoint=payload.endpoint,
                credential_reference=payload.credential_reference,
                local_cli_adapter=payload.local_cli_adapter,
                local_cli_command=payload.local_cli_command,
            )
        except TrustBoundaryError as exc:
            raise ApiError(400, "invalid_provider_profile", str(exc)) from exc
        profile_id = str(uuid.uuid4())
        await runtime.store.insert_provider_profile(
            profile_id=profile_id,
            name=payload.name,
            provider=payload.provider,
            credential_reference=payload.credential_reference,
            endpoint=payload.endpoint,
            local_cli_adapter=payload.local_cli_adapter,
            local_cli_command=payload.local_cli_command,
            adapter_label=payload.adapter_label,
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
        try:
            validate_provider_profile_shape(
                provider=payload.provider,
                endpoint=payload.endpoint,
                credential_reference=payload.credential_reference,
                local_cli_adapter=payload.local_cli_adapter,
                local_cli_command=payload.local_cli_command,
            )
        except TrustBoundaryError as exc:
            raise ApiError(400, "invalid_provider_profile", str(exc)) from exc
        await runtime.store.update_provider_profile(
            profile_id=profile_id,
            name=payload.name,
            provider=payload.provider,
            credential_reference=payload.credential_reference,
            endpoint=payload.endpoint,
            local_cli_adapter=payload.local_cli_adapter,
            local_cli_command=payload.local_cli_command,
            adapter_label=payload.adapter_label,
        )
        row = await runtime.store.get_provider_profile(profile_id)
        assert row is not None
        in_use = await runtime.store.provider_profile_in_use(profile_id)
        return present_provider_profile(row, referenced_by_history=in_use)

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
        """Honest connection pre-flight.

        This endpoint never pretends to run a provider health check. For a
        remote profile it performs *credential reference validation*
        (server-side environment resolution) and endpoint shape validation —
        no model call is made. For a local-cli profile it verifies the argv
        and that the executable resolves on PATH without running it.
        """
        runtime = _runtime(request)
        _mutation_guard(request, csrf_token)
        row = await runtime.store.get_provider_profile(profile_id)
        if row is None:
            raise ApiError(404, "provider_profile_not_found", "unknown provider profile")
        observed_at = datetime.now(UTC).isoformat()
        provider = str(row.get("provider") or "")
        if provider == "local-cli":
            argv = profile_command_argv(row)
            if not argv:
                return {
                    "ok": False,
                    "test_kind": "local_cli_executable_check",
                    "detail": "local-cli profile has no command argv",
                    "tested_at": observed_at,
                }
            resolved_executable = shutil.which(argv[0])
            if resolved_executable is None:
                return {
                    "ok": False,
                    "test_kind": "local_cli_executable_check",
                    "detail": f"executable {argv[0]!r} was not found on PATH (not executed)",
                    "tested_at": observed_at,
                }
            return {
                "ok": True,
                "test_kind": "local_cli_executable_check",
                "detail": (
                    f"argv is valid and {argv[0]!r} resolves to {resolved_executable}; "
                    "the command was not executed"
                ),
                "tested_at": observed_at,
            }
        reference = row.get("credential_reference")
        if not reference:
            return {
                "ok": False,
                "test_kind": "credential_reference_validation",
                "detail": "credential reference is not configured",
                "tested_at": observed_at,
            }
        try:
            name = parse_credential_reference(str(reference))
            resolve_credential_reference(str(reference))
        except TrustBoundaryError as exc:
            return {
                "ok": False,
                "test_kind": "credential_reference_validation",
                "detail": str(exc),
                "tested_at": observed_at,
            }
        endpoint = row.get("endpoint")
        return {
            "ok": True,
            "test_kind": "credential_reference_validation",
            "detail": (
                f"credential reference ${{{name}}} is set in the server environment; "
                f"endpoint {endpoint or 'provider default'} was validated by shape only — "
                "no provider call was made"
            ),
            "tested_at": observed_at,
        }

    @router.get("/api/v1/review-policies")
    async def list_review_policies(request: Request) -> list[dict[str, Any]]:
        runtime = _runtime(request)
        items = []
        for row in await runtime.store.list_trusted_policies("trusted_review_policies"):
            policy, identity = load_review_policy(Path(row["path"]))
            items.append(present_review_policy(row, policy, drifted=_policy_drifted(row, identity)))
        return items

    @router.post("/api/v1/review-policies", status_code=201)
    async def register_review_policy(
        payload: RegisterReviewPolicyRequest,
        request: Request,
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
    ) -> dict[str, Any]:
        """Register a trusted Review Policy from a server-side path.

        The policy must live outside every registered (reviewed) repository;
        the browser supplies a path, never policy content.
        """
        runtime = _runtime(request)
        _mutation_guard(request, csrf_token)
        try:
            row = await register_trusted_policy(runtime.store, Path(payload.path), kind="review")
        except (TrustBoundaryError, InvalidInvocationError) as exc:
            raise ApiError(400, "invalid_review_policy", str(exc)) from exc
        policy_id = str(row["id"])
        stored = await runtime.store.get_trusted_policy("trusted_review_policies", policy_id)
        assert stored is not None
        policy, identity = load_review_policy(Path(stored["path"]))
        return present_review_policy(stored, policy, drifted=_policy_drifted(stored, identity))

    @router.post("/api/v1/compute-policies", status_code=201)
    async def register_compute_policy(
        payload: RegisterComputePolicyRequest,
        request: Request,
        csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
    ) -> dict[str, Any]:
        """Register a trusted Compute Policy, optionally bound to a Provider Profile."""
        runtime = _runtime(request)
        _mutation_guard(request, csrf_token)
        try:
            row = await register_trusted_policy(
                runtime.store,
                Path(payload.path),
                kind="compute",
                provider_profile_id=payload.provider_profile_id,
            )
        except (TrustBoundaryError, InvalidInvocationError) as exc:
            raise ApiError(400, "invalid_compute_policy", str(exc)) from exc
        policy_id = str(row["id"])
        stored = await runtime.store.get_trusted_policy("trusted_compute_policies", policy_id)
        assert stored is not None
        policy = load_trusted_compute_document(Path(stored["path"]))[0]
        return present_compute_policy(
            stored, policy, provider_profile_name=await _bound_profile_name(runtime, stored)
        )

    @router.get("/api/v1/review-policies/{policy_id}")
    async def get_review_policy(policy_id: str, request: Request) -> dict[str, Any]:
        runtime = _runtime(request)
        row = await runtime.store.get_trusted_policy("trusted_review_policies", policy_id)
        if row is None:
            raise ApiError(404, "review_policy_not_found", "unknown review policy")
        policy, identity = load_review_policy(Path(row["path"]))
        return present_review_policy(row, policy, drifted=_policy_drifted(row, identity))

    @router.get("/api/v1/compute-policies")
    async def list_compute_policies(request: Request) -> list[dict[str, Any]]:
        runtime = _runtime(request)
        items = []
        for row in await runtime.store.list_trusted_policies("trusted_compute_policies"):
            policy, identity, _format = load_trusted_compute_document(Path(row["path"]))
            items.append(
                present_compute_policy(
                    row,
                    policy,
                    provider_profile_name=await _bound_profile_name(runtime, row),
                    drifted=_policy_drifted(row, identity),
                )
            )
        return items

    @router.get("/api/v1/compute-policies/{policy_id}")
    async def get_compute_policy(policy_id: str, request: Request) -> dict[str, Any]:
        runtime = _runtime(request)
        row = await runtime.store.get_trusted_policy("trusted_compute_policies", policy_id)
        if row is None:
            raise ApiError(404, "compute_policy_not_found", "unknown compute policy")
        policy, identity, _fmt = load_trusted_compute_document(Path(row["path"]))
        return present_compute_policy(
            row,
            policy,
            provider_profile_name=await _bound_profile_name(runtime, row),
            drifted=_policy_drifted(row, identity),
        )

    return router
