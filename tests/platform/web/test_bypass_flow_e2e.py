"""Authorized-mode HTTP flow: login → session → per-finding bypass → audit →
Detail standing projection, all over one FastAPI app (P3 §12.3)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest

from worktree_review.core.identity import (
    MergeCandidateIdentity,
    PolicyVersionIdentity,
    ResolvedCommitPair,
    ReviewIdentity,
    ReviewRequestKey,
)
from worktree_review.core.report import (
    ComputePolicyDisclosure,
    CoverageRecord,
    ExecutionRecord,
    GateState,
    ReviewReport,
    StageName,
    StageOutcome,
    StageStatus,
)
from worktree_review.platform.cli.result import cli_result_document
from worktree_review.platform.github.authz import GitHubRoleBypassAuthorizer
from worktree_review.platform.github.bypass import GitHubBypassCoordinator
from worktree_review.platform.github.persistence import InMemoryGitHubReviewStore
from worktree_review.platform.github.triggers import build_frozen_execution_snapshot
from worktree_review.platform.web.authentication import (
    SESSION_COOKIE_NAME,
    GitHubAuthenticatedUser,
    GitHubWebAuthenticator,
    WebAuthConfiguration,
)
from worktree_review.server.state import (
    GitHubChangeRequestLocator,
    InMemoryAuthoritativeAttemptStore,
)

pytest.importorskip("fastapi")

_LOCATOR = GitHubChangeRequestLocator(
    installation_id=7, repository="octo/example", pull_request_number=42
)

_COMPLETE_OUTCOMES = tuple(
    StageOutcome(stage=stage, status=StageStatus.COMPLETED)
    for stage in (
        StageName.DERIVE_IDENTITY,
        StageName.CONSTRUCT_MERGE,
        StageName.GATHER_CONTEXT,
        StageName.RUN_DIMENSIONS,
        StageName.VERIFY_DEDUP,
        StageName.CHECK_COMPLETENESS,
        StageName.EVALUATE_GATE,
    )
)


class _StubOAuthTransport:
    def __init__(self) -> None:
        self.user_lookups = 0

    async def exchange_code_for_user_token(self, *, code: str, code_verifier: str) -> str:
        return "flow-user-token"

    async def get_authenticated_user(self, *, user_token: str) -> GitHubAuthenticatedUser:
        self.user_lookups += 1
        return GitHubAuthenticatedUser(user_id=42, login="octocat")


class _WriteRoleLookup:
    async def repository_role(
        self, *, installation_id: int, repository: str, actor: str
    ) -> str | None:
        return "write"


def _blocked_report(attempt_id: str, request_key: ReviewRequestKey) -> ReviewReport:
    from tests.platform.test_github_bypass import _finding

    return ReviewReport(
        gate_state=GateState.BLOCKED,
        attempt_id=attempt_id,
        request_key=request_key,
        resolved=ResolvedCommitPair(
            source_repository="octo/example",
            target_ref="main",
            target_head_oid="a" * 40,
            proposed_ref="feature",
            proposed_head_oid="b" * 40,
        ),
        merge_tree_oid="c" * 40,
        review_identity=ReviewIdentity(
            candidate=MergeCandidateIdentity(
                source_repository="octo/example",
                target_ref="main",
                target_head_oid="a" * 40,
                proposed_head_oid="b" * 40,
                merge_tree_oid="c" * 40,
            ),
            review_policy_version=request_key.review_policy_version,
        ),
        review_policy_version=request_key.review_policy_version,
        compute_policy_version=PolicyVersionIdentity(semver="1.0.0", sha256="e" * 64),
        compute_policy_disclosure=ComputePolicyDisclosure(
            provider="anthropic",
            model="claude",
            data_destination="https://api.anthropic.com",
            known_retention="none",
        ),
        execution=ExecutionRecord(outcomes=_COMPLETE_OUTCOMES),
        findings=(_finding("fp-1"), _finding("fp-2")),
        coverage=CoverageRecord(
            required_coverage_complete=True,
            reviewed=("src/webhooks/verify.py",),
        ),
        summary="review complete",
    )


@pytest.fixture
def flow(policy_dir: Path) -> Any:
    """One FastAPI app in authorized mode with in-memory platform stores."""

    import asyncio

    import httpx
    from fastapi.testclient import TestClient

    from worktree_review.core.policy import load_review_policy
    from worktree_review.platform.github.retry import GitHubRetryCoordinator
    from worktree_review.platform.github.runtime import ServerRuntime
    from worktree_review.server.app import create_app

    _policy, policy_version = load_review_policy(policy_dir / "review-policy.yaml")
    request_key = ReviewRequestKey(
        source_repository="octo/example",
        target_ref="main",
        target_head_oid="a" * 40,
        proposed_head_oid="b" * 40,
        review_policy_version=policy_version,
    )

    state = InMemoryAuthoritativeAttemptStore()
    store = InMemoryGitHubReviewStore()
    transport = _StubOAuthTransport()
    authenticator = GitHubWebAuthenticator(
        config=WebAuthConfiguration(
            public_base_url="https://reviews.example.com",
            github_oauth_client_id="Iv1.testclient",
            github_oauth_client_secret="secret-value",
        ),
        transport=transport,
    )
    coordinator = GitHubBypassCoordinator(
        state=state,
        github_store=store,
        authorizer=GitHubRoleBypassAuthorizer(_WriteRoleLookup()),
        review_policy_path=policy_dir / "review-policy.yaml",
    )

    class _NoopAuthorizer:
        async def may_retry(self, *, change_request: object, actor: str) -> bool:
            return False

    class _NoopResolver:
        async def resolve_current_request(self, change_request: object) -> Any:
            raise AssertionError("not used")

    runtime = ServerRuntime(
        retry_coordinator=GitHubRetryCoordinator(
            state=state, authorizer=_NoopAuthorizer(), resolver=_NoopResolver()
        ),
        database_pool=None,  # type: ignore[arg-type]
        http_client=httpx.AsyncClient(),
        github_store=store,  # type: ignore[arg-type]
        attempt_store=state,  # type: ignore[arg-type]
        web_authenticator=authenticator,
        bypass_coordinator=coordinator,
        role_lookup=_WriteRoleLookup(),
    )
    application = create_app(enable_local_web=False)
    application.state.server_runtime = runtime

    async def _seed_blocked_attempt() -> str:
        lease = await state.start_authoritative_attempt(
            change_request=_LOCATOR, request_key=request_key
        )
        report = _blocked_report(lease.attempt_id, request_key)
        await state.record_review_identity(
            attempt_id=lease.attempt_id, review_identity=report.review_identity
        )
        await state.claim_attempt_job(lease.attempt_id)
        await store.save_execution_snapshot(
            build_frozen_execution_snapshot(
                attempt_id=lease.attempt_id,
                change_request=_LOCATOR,
                request_key=request_key,
                proposed_ref="feature",
                review_policy_path=policy_dir / "review-policy.yaml",
                compute_policy_path=policy_dir / "compute-policy.yaml",
            )
        )
        await store.set_check_run_id(lease.attempt_id, 98765)
        from worktree_review.application.lifecycle import PublicationStatus

        await store.mark_publication(lease.attempt_id, status=PublicationStatus.PUBLISHED)
        await store.save_review_result(
            lease.attempt_id, cli_result_document(report).model_dump_json(by_alias=True)
        )
        await state.publish_if_authoritative(
            attempt_id=lease.attempt_id,
            request_key=request_key,
            review_identity=report.review_identity,
            gate_state=GateState.BLOCKED,
        )
        return lease.attempt_id

    attempt_id = asyncio.run(_seed_blocked_attempt())
    return {
        "attempt_id": attempt_id,
        "transport": transport,
        "client": TestClient(application, base_url="http://127.0.0.1"),
    }


def _login(client: Any) -> dict[str, str]:
    start = client.get("/api/v1/auth/github/start", follow_redirects=False)
    state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
    nonce = re.search(r"wr_login_nonce=([^;]+)", start.headers["set-cookie"])
    assert nonce is not None
    callback = client.get(
        "/api/v1/auth/github/callback",
        params={"code": "code-1", "state": state},
        headers={"Cookie": f"wr_login_nonce={nonce.group(1)}"},
        follow_redirects=False,
    )
    cookie_value = re.search(rf"{SESSION_COOKIE_NAME}=([^;]+)", callback.headers["set-cookie"])
    assert cookie_value is not None
    cookie_header = f"{SESSION_COOKIE_NAME}={cookie_value.group(1)}"
    session = client.get("/api/v1/auth/session", headers={"Cookie": cookie_header})
    return {"Cookie": cookie_header, "X-CSRF-Token": session.json()["csrf_token"]}


def test_authorized_bypass_flow_end_to_end(flow: Any) -> None:
    client = flow["client"]
    attempt_id = flow["attempt_id"]

    # Unauthenticated: the mutation is refused before any state lookup.
    anonymous = client.post(
        f"/api/v1/reviews/{attempt_id}/findings/fp-1/bypass", json={"reason": "ok"}
    )
    assert anonymous.status_code == 401

    headers = _login(client)
    origin = {"Origin": "https://reviews.example.com"}

    # Accept the first of two blocking findings: still Blocked, sync queued.
    first = client.post(
        f"/api/v1/reviews/{attempt_id}/findings/fp-1/bypass",
        json={"reason": "Isolated legacy endpoint; removal scheduled for Q4."},
        headers={**headers, **origin},
    )
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["standing_gate_state"] == "Blocked"
    assert body["remaining_blocking_count"] == 1
    assert body["gate_transitioned"] is False
    assert body["check_sync_status"] == "queued"

    # The second acceptance transitions the standing gate.
    second = client.post(
        f"/api/v1/reviews/{attempt_id}/findings/fp-2/bypass",
        json={"reason": "Same acceptance: tracked removal covers both."},
        headers={**headers, **origin},
    )
    assert second.status_code == 200
    assert second.json()["standing_gate_state"] == "Passed with bypass"
    assert second.json()["gate_transitioned"] is True

    # Every action re-verified the GitHub identity (login + 2 bypasses).
    assert flow["transport"].user_lookups >= 3

    # The Detail projection reports Core and standing side by side.
    detail = client.get(f"/api/v1/reviews/{attempt_id}", headers={"Cookie": headers["Cookie"]})
    assert detail.status_code == 200
    dto = detail.json()
    assert dto["core_gate_state"] == "Blocked"
    assert dto["standing_gate_state"] == "Passed with bypass"
    assert dto["bypass_state"] == "active"
    assert dto["gate"]["remaining_blocking_fingerprints"] == []
    findings = {finding["fingerprint"]: finding for finding in dto["findings"]}
    assert findings["fp-1"]["bypass_record"]["actor_login"] == "octocat"
    # The immutable findings stay visible — nothing was resolved away.
    assert findings["fp-1"]["blocking"] is True

    # The audit log (repository-scoped) explains who accepted what.
    audit = client.get(
        "/api/v1/audit-events",
        params={"repository": "octo/example", "event_type": "bypass_authorized"},
        headers={"Cookie": headers["Cookie"]},
    )
    assert audit.status_code == 200
    events = audit.json()["events"]
    assert len(events) == 2
    assert {event["payload"]["finding_fingerprint"] for event in events} == {"fp-1", "fp-2"}
    assert all(event["actor_login"] == "octocat" for event in events)
    assert all(event["actor_id"] == 42 for event in events)
    # The user token never leaks into audit payloads.
    assert "flow-user-token" not in audit.text


def test_audit_events_require_repository_scope(flow: Any) -> None:
    client = flow["client"]
    headers = _login(client)
    unscoped = client.get("/api/v1/audit-events", headers={"Cookie": headers["Cookie"]})
    assert unscoped.status_code == 400
    assert unscoped.json()["error"]["code"] == "repository_required"
