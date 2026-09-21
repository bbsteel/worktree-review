"""Append-only audit events: typed model, payload safety, pagination, API (D9)."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from tests.platform.postgres_harness import database_url_for_name, open_postgres_url

from worktree_review.server.audit import (
    MAX_AUDIT_EVENTS_PER_PAGE,
    AuditEventType,
    assert_safe_audit_payload,
    parse_audit_cursor,
)
from worktree_review.server.state import (
    GitHubChangeRequestLocator,
    InMemoryAuthoritativeAttemptStore,
    PostgresAuthoritativeAttemptStore,
)


def _locator(**overrides: Any) -> GitHubChangeRequestLocator:
    fields: dict[str, Any] = {
        "installation_id": 7,
        "repository": "octo/example",
        "pull_request_number": 42,
    }
    fields.update(overrides)
    return GitHubChangeRequestLocator(**fields)


async def _append(
    store: InMemoryAuthoritativeAttemptStore,
    event_type: str,
    *,
    locator: GitHubChangeRequestLocator | None = None,
    attempt_id: str | None = None,
    actor_id: int | None = None,
    actor_login: str | None = None,
    payload: dict[str, object] | None = None,
) -> None:
    await store.append_audit_event(
        event_type=event_type,
        change_request=locator or _locator(),
        attempt_id=attempt_id,
        payload=payload or {},
        actor_id=actor_id,
        actor_login=actor_login,
    )


@pytest.mark.asyncio
async def test_list_audit_events_is_newest_first_and_paginates() -> None:
    store = InMemoryAuthoritativeAttemptStore()
    for index in range(5):
        await _append(store, f"event_{index}", attempt_id=f"attempt-{index}")

    first = await store.list_audit_events(limit=2)
    assert [event.event_type for event in first.events] == ["event_4", "event_3"]
    assert first.next_cursor is not None

    second = await store.list_audit_events(limit=2, cursor=first.next_cursor)
    assert [event.event_type for event in second.events] == ["event_2", "event_1"]
    assert second.next_cursor is not None

    third = await store.list_audit_events(limit=2, cursor=second.next_cursor)
    assert [event.event_type for event in third.events] == ["event_0"]
    assert third.next_cursor is None

    # Pages are disjoint and cover every event exactly once.
    seen = [event.event_id for page in (first, second, third) for event in page.events]
    assert sorted(seen) == [1, 2, 3, 4, 5]


@pytest.mark.asyncio
async def test_list_audit_events_filters() -> None:
    store = InMemoryAuthoritativeAttemptStore()
    await _append(store, "retry_authorized", attempt_id="a-1", actor_login="maintainer")
    await _append(store, "bypass_authorized", attempt_id="a-1", actor_login="maintainer")
    await _append(store, "retry_authorized", attempt_id="a-2", actor_login="reviewer")
    await _append(
        store,
        "retry_authorized",
        locator=_locator(repository="octo/other", pull_request_number=9),
    )

    by_type = await store.list_audit_events(event_type="retry_authorized")
    assert len(by_type.events) == 3
    by_attempt = await store.list_audit_events(attempt_id="a-1")
    assert [event.event_type for event in by_attempt.events] == [
        "bypass_authorized",
        "retry_authorized",
    ]
    by_repository = await store.list_audit_events(repository="octo/other")
    assert len(by_repository.events) == 1
    by_pr = await store.list_audit_events(pull_request_number=9)
    assert len(by_pr.events) == 1
    assert by_pr.events[0].repository == "octo/other"
    actor = by_type.events[-1]
    assert actor.actor_login == "maintainer"


@pytest.mark.asyncio
async def test_list_audit_events_filters_by_installation_ids() -> None:
    store = InMemoryAuthoritativeAttemptStore()
    await _append(store, "bypass_authorized", locator=_locator(installation_id=7))
    await _append(store, "bypass_authorized", locator=_locator(installation_id=99))
    await _append(store, "bypass_authorized", locator=_locator(installation_id=7))

    scoped = await store.list_audit_events(repository="octo/example", installation_ids=(7,))
    assert len(scoped.events) == 2
    assert {event.installation_id for event in scoped.events} == {7}

    empty = await store.list_audit_events(repository="octo/example", installation_ids=())
    assert empty.events == ()


@pytest.mark.asyncio
async def test_list_audit_events_rejects_invalid_cursor_and_clamps_limit() -> None:
    store = InMemoryAuthoritativeAttemptStore()
    await _append(store, "attempt_authoritative")

    with pytest.raises(ValueError, match="invalid audit event cursor"):
        await store.list_audit_events(cursor="not-a-cursor")
    with pytest.raises(ValueError, match="invalid audit event cursor"):
        await store.list_audit_events(cursor="0")

    clamped = await store.list_audit_events(limit=MAX_AUDIT_EVENTS_PER_PAGE + 500)
    assert len(clamped.events) == 1


def test_parse_audit_cursor_accepts_positive_ids() -> None:
    assert parse_audit_cursor(None) is None
    assert parse_audit_cursor("17") == 17


def test_payload_safety_rejects_secret_shaped_keys() -> None:
    assert_safe_audit_payload({"reason": "ok", "request_key": {"target_ref": "main"}})

    for payload in (
        {"token": "abc"},
        {"api_key": "abc"},
        {"nested": {"access_token": "abc"}},
        {"items": [{"webhook_secret": "abc"}]},
        {"X": {"authorization": "Bearer abc"}},
    ):
        with pytest.raises(ValueError, match="forbidden key"):
            assert_safe_audit_payload(payload)


def test_payload_safety_rejects_secret_shaped_values() -> None:
    assert_safe_audit_payload({"detail": "the deploy failed twice"})

    # Token formats are caught even under innocuous key names.
    with pytest.raises(ValueError, match="secret-shaped content"):
        assert_safe_audit_payload({"detail": "saw ghp_abcdefghijklmnop0123 in the log"})
    with pytest.raises(ValueError, match="secret-shaped content"):
        assert_safe_audit_payload({"nested": {"items": ["sk-ant-abcdefghijklmnop"]}})


def test_payload_safety_rejects_current_env_credential_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WR_TEST_PROVIDER_API_KEY", "unique-credential-value-123")
    with pytest.raises(ValueError, match="secret-shaped content"):
        assert_safe_audit_payload({"detail": "leaked unique-credential-value-123 here"})
    # Unrelated text mentioning neither patterns nor env values stays writable.
    assert_safe_audit_payload({"detail": "unique credentials rotated"})


def test_payload_safety_rejects_non_serializable_and_oversized() -> None:
    with pytest.raises(ValueError, match="JSON-serializable"):
        assert_safe_audit_payload({"when": object()})
    with pytest.raises(ValueError, match="maximum size"):
        assert_safe_audit_payload({"detail": "x" * (40 * 1024)})


@pytest.mark.asyncio
async def test_append_audit_event_validates_payload_before_persisting() -> None:
    store = InMemoryAuthoritativeAttemptStore()
    with pytest.raises(ValueError, match="forbidden key"):
        await _append(store, "retry_authorized", payload={"github_token": "abc"})
    assert (await store.list_audit_events()).events == ()


@pytest.mark.asyncio
async def test_audit_events_dict_view_stays_back_compatible() -> None:
    store = InMemoryAuthoritativeAttemptStore()
    await _append(
        store, "retry_denied", attempt_id="a-1", actor_id=123456, actor_login="maintainer"
    )

    events = await store.audit_events()
    assert events[0]["event_type"] == "retry_denied"
    assert events[0]["attempt_id"] == "a-1"
    assert events[0]["actor_id"] == 123456
    assert events[0]["actor_login"] == "maintainer"


@pytest.fixture(scope="module")
def postgres_base_url() -> Any:
    yield from open_postgres_url()


@pytest.fixture
async def postgres_store(postgres_base_url: str) -> Any:
    asyncpg = pytest.importorskip("asyncpg")
    import asyncio

    name = f"wr_audit_{uuid.uuid4().hex[:12]}"
    connection = await asyncpg.connect(postgres_base_url)
    try:
        await connection.execute(f"CREATE DATABASE {name}")
    finally:
        await connection.close()
    pool = await asyncpg.create_pool(
        database_url_for_name(postgres_base_url, name),
        statement_cache_size=0,
    )
    try:
        store = PostgresAuthoritativeAttemptStore(pool)
        await store.initialise()
        yield store
    finally:
        await pool.close()
        await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_postgres_audit_events_round_trip_and_paginate(postgres_store: Any) -> None:
    store = postgres_store
    for index in range(3):
        await store.append_audit_event(
            event_type="retry_authorized" if index < 2 else "bypass_authorized",
            change_request=_locator(),
            attempt_id=str(uuid.uuid4()),
            actor_id=123456,
            actor_login="maintainer",
            payload={"index": index},
        )

    first = await store.list_audit_events(limit=2)
    assert [event.payload["index"] for event in first.events] == [2, 1]
    assert first.events[0].actor_id == 123456
    assert first.events[0].actor_login == "maintainer"
    assert first.next_cursor is not None
    second = await store.list_audit_events(limit=2, cursor=first.next_cursor)
    assert [event.payload["index"] for event in second.events] == [0]
    assert second.next_cursor is None

    filtered = await store.list_audit_events(event_type=AuditEventType.BYPASS_AUTHORIZED.value)
    assert [event.payload["index"] for event in filtered.events] == [2]

    with pytest.raises(ValueError, match="forbidden key"):
        await store.append_audit_event(
            event_type="retry_authorized",
            change_request=_locator(),
            attempt_id=None,
            payload={"session_token": "abc"},
        )
    with pytest.raises(ValueError, match="secret-shaped content"):
        await store.append_audit_event(
            event_type="retry_authorized",
            change_request=_locator(),
            attempt_id=None,
            payload={"detail": "token ghp_abcdefghijklmnop0123 appeared"},
        )


def test_audit_api_requires_platform_store() -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from worktree_review.server.app import create_app

    application = create_app(enable_local_web=False)
    with TestClient(application, base_url="http://127.0.0.1") as client:
        response = client.get("/api/v1/audit-events", params={"repository": "octo/example"})
    assert response.status_code == 501
    assert response.json()["error"]["code"] == "capability_unavailable"


def test_audit_api_requires_repository_filter() -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from worktree_review.server.app import create_app

    application = create_app(enable_local_web=False)
    application.state.server_runtime = _runtime_with_store(InMemoryAuthoritativeAttemptStore())
    with TestClient(application, base_url="http://127.0.0.1") as client:
        response = client.get("/api/v1/audit-events")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "repository_required"


def _runtime_with_store(attempt_store: InMemoryAuthoritativeAttemptStore) -> Any:
    import httpx

    from worktree_review.platform.github.retry import GitHubRetryCoordinator
    from worktree_review.platform.github.runtime import ServerRuntime

    class _NoopAuthorizer:
        async def may_retry(self, *, change_request: object, actor: str) -> bool:
            return False

    class _NoopResolver:
        async def resolve_current_request(self, change_request: object) -> Any:
            raise AssertionError("not used")

    return ServerRuntime(
        retry_coordinator=GitHubRetryCoordinator(
            state=attempt_store,
            authorizer=_NoopAuthorizer(),
            resolver=_NoopResolver(),
        ),
        database_pool=None,  # never touched by the read-only audit endpoint
        http_client=httpx.AsyncClient(),
        attempt_store=attempt_store,  # type: ignore[arg-type]
    )


def test_audit_api_paginates_and_never_mutates() -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from worktree_review.server.app import create_app

    attempt_store = InMemoryAuthoritativeAttemptStore()
    import asyncio

    async def _seed() -> None:
        for index in range(3):
            await _append(attempt_store, f"event_{index}", actor_login="maintainer")
        await _append(
            attempt_store,
            "other_repo_event",
            locator=_locator(repository="octo/other"),
        )

    asyncio.run(_seed())
    application = create_app(enable_local_web=False)
    application.state.server_runtime = _runtime_with_store(attempt_store)
    with TestClient(application, base_url="http://127.0.0.1") as client:
        page_one = client.get(
            "/api/v1/audit-events", params={"repository": "octo/example", "limit": 2}
        )
        assert page_one.status_code == 200
        assert page_one.headers["Cache-Control"] == "no-store"
        body = page_one.json()
        # The mandatory repository filter excludes the other repository's event.
        assert [event["event_type"] for event in body["events"]] == ["event_2", "event_1"]
        assert body["events"][0]["actor_login"] == "maintainer"
        assert body["events"][0]["repository"] == "octo/example"
        assert body["next_cursor"] is not None

        page_two = client.get(
            "/api/v1/audit-events",
            params={"repository": "octo/example", "limit": 2, "cursor": body["next_cursor"]},
        )
        assert [event["event_type"] for event in page_two.json()["events"]] == ["event_0"]
        assert page_two.json()["next_cursor"] is None

        invalid = client.get(
            "/api/v1/audit-events", params={"repository": "octo/example", "cursor": "bogus"}
        )
        assert invalid.status_code == 400
        assert invalid.json()["error"]["code"] == "invalid_cursor"

        for method in (client.post, client.put, client.patch, client.delete):
            mutation = method("/api/v1/audit-events", params={"repository": "octo/example"})
            assert mutation.status_code == 405
