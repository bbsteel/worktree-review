"""PM-101: frontend packaging resolution order.

An installed wheel serves the bundle from the package's own ``static``
directory; a source checkout falls back to ``frontend/dist``; an explicit
``WORKTREE_REVIEW_FRONTEND_DIST`` always wins.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from worktree_review.server import app as server_app


def test_env_override_wins(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    override = tmp_path / "custom-dist"
    monkeypatch.setenv("WORKTREE_REVIEW_FRONTEND_DIST", str(override))
    assert server_app.default_frontend_dist() == override


def test_packaged_static_is_preferred_when_present(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("WORKTREE_REVIEW_FRONTEND_DIST", raising=False)
    packaged = tmp_path / "static"
    packaged.mkdir()
    (packaged / "index.html").write_text("<html></html>", encoding="utf-8")
    monkeypatch.setattr(server_app, "packaged_frontend_dist", lambda: packaged)
    assert server_app.default_frontend_dist() == packaged


def test_source_checkout_fallback_when_not_packaged(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("WORKTREE_REVIEW_FRONTEND_DIST", raising=False)
    monkeypatch.setattr(server_app, "packaged_frontend_dist", lambda: tmp_path / "absent")
    expected = Path(server_app.__file__).resolve().parents[3] / "frontend" / "dist"
    assert server_app.default_frontend_dist() == expected


def test_missing_build_error_names_the_sync_script(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="sync_frontend_dist"):
        server_app.require_frontend_dist(tmp_path / "no-dist")
