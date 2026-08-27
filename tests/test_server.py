from __future__ import annotations

import pytest

pytest.importorskip("fastapi")


def test_healthz() -> None:
    from fastapi.testclient import TestClient

    from worktree_review.server.app import create_app

    client = TestClient(create_app())
    response = client.get("/healthz")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "version" in body


def test_github_webhook_is_not_implemented() -> None:
    from fastapi.testclient import TestClient

    from worktree_review.server.app import create_app

    client = TestClient(create_app())
    response = client.post("/webhooks/github", content=b"{}")
    assert response.status_code == 501
