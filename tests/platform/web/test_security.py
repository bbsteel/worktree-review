"""CSRF bootstrap and exact Origin/Host validation for local Web mutations."""

from __future__ import annotations

from pathlib import Path

import pytest

from worktree_review.platform.web.runtime import open_web_runtime
from worktree_review.platform.web.security import is_loopback_origin
from worktree_review.server.app import create_app

pytest.importorskip("fastapi")


@pytest.mark.asyncio
async def test_csrf_bootstrap_issues_token_that_authorizes_mutations(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    runtime = await open_web_runtime(tmp_path / "csrf.sqlite")
    application = create_app(web_runtime=runtime, enable_local_web=False)
    with TestClient(application, base_url="http://127.0.0.1") as client:
        bootstrap = client.get("/api/v1/csrf-bootstrap")
        assert bootstrap.status_code == 200
        assert bootstrap.headers.get("cache-control") == "no-store"
        token = bootstrap.json()["csrf_token"]
        assert isinstance(token, str) and len(token) >= 32
        assert token == runtime.csrf_token

        missing = client.post("/api/v1/repositories", json={"path": "/tmp/nope"})
        assert missing.status_code == 403
        assert missing.json()["error"]["code"] == "missing_csrf_token"

        wrong = client.post(
            "/api/v1/repositories",
            json={"path": "/tmp/nope"},
            headers={"X-CSRF-Token": "not-the-server-token"},
        )
        assert wrong.status_code == 403
        assert wrong.json()["error"]["code"] == "invalid_csrf_token"

        # The bootstrapped token passes the guard; registration then fails
        # only because the path is not a repository (400, not 403).
        accepted = client.post(
            "/api/v1/repositories",
            json={"path": str(tmp_path / "missing-repository")},
            headers={"X-CSRF-Token": token, "Origin": "http://127.0.0.1"},
        )
        assert accepted.status_code == 400
        assert accepted.json()["error"]["code"] == "invalid_repository"


@pytest.mark.asyncio
async def test_csrf_bootstrap_is_loopback_only(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    runtime = await open_web_runtime(tmp_path / "csrf-host.sqlite")
    application = create_app(web_runtime=runtime, enable_local_web=False)
    remote = TestClient(application, base_url="http://example.com")
    with remote:
        denied = remote.get("/api/v1/csrf-bootstrap")
        assert denied.status_code == 403
        assert denied.json()["error"]["code"] == "forbidden_host"


@pytest.mark.asyncio
async def test_cross_origin_mutation_with_stolen_looking_origin_is_rejected(
    tmp_path: Path,
) -> None:
    from fastapi.testclient import TestClient

    runtime = await open_web_runtime(tmp_path / "csrf-origin.sqlite")
    application = create_app(web_runtime=runtime, enable_local_web=False)
    with TestClient(application, base_url="http://127.0.0.1") as client:
        token = client.get("/api/v1/csrf-bootstrap").json()["csrf_token"]
        for evil_origin in (
            "http://localhost.evil.example",
            "http://127.0.0.1.evil.example",
            "https://127.0.0.1.attacker.invalid:8443",
            "ftp://127.0.0.1",
            "null",
        ):
            response = client.post(
                "/api/v1/repositories",
                json={"path": "/tmp/nope"},
                headers={"X-CSRF-Token": token, "Origin": evil_origin},
            )
            assert response.status_code == 403, evil_origin
            assert response.json()["error"]["code"] == "forbidden_origin", evil_origin


def test_origin_hostname_is_parsed_not_prefix_matched() -> None:
    assert is_loopback_origin("http://localhost")
    assert is_loopback_origin("http://localhost:8080")
    assert is_loopback_origin("http://127.0.0.1:8000")
    assert is_loopback_origin(None)
    assert not is_loopback_origin("http://localhost.evil.example")
    assert not is_loopback_origin("http://localhost@evil.example")
    assert not is_loopback_origin("http://127.0.0.1.evil.example")
    assert not is_loopback_origin("javascript://localhost")
    assert not is_loopback_origin("null")
