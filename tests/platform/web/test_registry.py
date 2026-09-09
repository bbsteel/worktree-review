from __future__ import annotations

from pathlib import Path

import pytest

from worktree_review.platform.web.local_store import SqliteReviewRunStore
from worktree_review.platform.web.registry import (
    TrustBoundaryError,
    parse_credential_reference,
    register_local_repository,
    register_trusted_policy,
    require_registered_repository_path,
    resolve_credential_reference,
)


async def _store(tmp_path: Path) -> SqliteReviewRunStore:
    store = SqliteReviewRunStore(tmp_path / "review.sqlite")
    await store.migrate()
    return store


@pytest.mark.asyncio
async def test_unregistered_path_is_rejected(tmp_path: Path, git_repository: Path) -> None:
    store = await _store(tmp_path)
    await register_local_repository(
        store, requested_root=git_repository, display_name="demo"
    )
    outsider = tmp_path / "other"
    outsider.mkdir()
    with pytest.raises(TrustBoundaryError, match="not a registered"):
        await require_registered_repository_path(store, outsider)


@pytest.mark.asyncio
async def test_policy_inside_repository_is_rejected(tmp_path: Path, git_repository: Path) -> None:
    store = await _store(tmp_path)
    await register_local_repository(
        store, requested_root=git_repository, display_name="demo"
    )
    inside = git_repository / "review-policy.yaml"
    inside.write_text(
        "schema: worktree-review.review-policy/v1\nversion: 0.1.0\n",
        encoding="utf-8",
    )
    with pytest.raises(TrustBoundaryError, match="inside a reviewed repository"):
        await register_trusted_policy(store, inside, kind="review")


def test_credential_reference_never_holds_secret_value(monkeypatch: pytest.MonkeyPatch) -> None:
    parse_credential_reference("${OPENAI_API_KEY}")
    with pytest.raises(TrustBoundaryError):
        parse_credential_reference("sk-live-secret")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-live-secret")
    assert resolve_credential_reference("${OPENAI_API_KEY}") == "sk-live-secret"
