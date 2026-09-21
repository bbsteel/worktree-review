from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from worktree_review.application.review_events import ReviewEvent
from worktree_review.platform.session_insight.journal import SessionJournalWriter
from worktree_review.server.app import DEFAULT_BIND_HOST, create_app, require_frontend_dist


def _event(attempt_id: str, sequence: int) -> ReviewEvent:
    return ReviewEvent(
        sequence=sequence,
        occurred_at=datetime.now(UTC),
        attempt_id=attempt_id,
        surface="web",
        event_type="attempt.created" if sequence == 1 else "stage.started",
        payload={},
    )


def test_journal_is_append_only_and_result_is_immutable(tmp_path: Path) -> None:
    writer = SessionJournalWriter(tmp_path / "sessions")
    writer.append_event(_event("a1", 1))
    writer.append_event(_event("a1", 2))
    writer.write_result("a1", '{"schema":"worktree-review.cli.result/v1","ok":true}')
    writer.write_result("a1", '{"schema":"worktree-review.cli.result/v1","ok":false}')
    events = (tmp_path / "sessions" / "a1" / "events.jsonl").read_text(encoding="utf-8")
    assert events.count("\n") == 2
    result = (tmp_path / "sessions" / "a1" / "result.json").read_text(encoding="utf-8")
    assert '"ok":true' in result
    metadata = (tmp_path / "sessions" / "a1" / "metadata.json").read_text(encoding="utf-8")
    assert "worktree-review.session-metadata/v1" in metadata
    assert '"last_persisted_sequence": 2' in metadata


def test_journal_backfill_skips_existing_sequences(tmp_path: Path) -> None:
    writer = SessionJournalWriter(tmp_path / "sessions")
    writer.append_event(_event("a1", 1))
    writer.backfill((_event("a1", 1), _event("a1", 2), _event("a1", 3)))
    lines = (tmp_path / "sessions" / "a1" / "events.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3


@pytest.mark.asyncio
async def test_journal_failure_warns_instead_of_raising(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    writer = SessionJournalWriter(tmp_path / "sessions")

    def _boom(*_args: object, **_kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(writer, "append_event", _boom)
    await writer.publish(_event("a1", 1))


def test_missing_frontend_dist_is_a_startup_error(tmp_path: Path) -> None:
    missing = tmp_path / "no-dist"
    with pytest.raises(RuntimeError, match="frontend production build is missing"):
        require_frontend_dist(missing)
    with pytest.raises(RuntimeError, match="frontend production build is missing"):
        create_app(
            enable_local_web=True,
            start_worker=False,
            serve_frontend=True,
            frontend_dist=missing,
        )


def test_frontend_index_is_served_and_bind_defaults_to_loopback(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    dist = tmp_path / "dist"
    assets = dist / "assets"
    assets.mkdir(parents=True)
    (dist / "index.html").write_text("<html>web ui</html>", encoding="utf-8")
    (assets / "app.js").write_text("console.log('ok')", encoding="utf-8")
    application = create_app(
        enable_local_web=True,
        start_worker=False,
        serve_frontend=True,
        frontend_dist=dist,
    )
    with TestClient(application, base_url="http://127.0.0.1") as client:
        index = client.get("/")
        assert index.status_code == 200
        assert "web ui" in index.text
        spa = client.get("/reviews/abc")
        assert spa.status_code == 200
        assert "web ui" in spa.text
        health = client.get("/healthz")
        assert health.status_code == 200
    assert DEFAULT_BIND_HOST == "127.0.0.1"
