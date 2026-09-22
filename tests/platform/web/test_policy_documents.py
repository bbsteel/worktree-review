"""Trusted Policy document read/write, managed create, and unregister."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
import yaml

from worktree_review.platform.web import registry as policy_registry
from worktree_review.platform.web.registry import (
    TrustBoundaryError,
    create_managed_trusted_policy,
    managed_policies_root,
    policy_document_content_sha256,
    read_trusted_policy_document,
    register_local_repository,
    register_trusted_policy,
    unregister_trusted_policy,
    write_trusted_policy_document,
)
from worktree_review.platform.web.runtime import open_web_runtime
from worktree_review.server.app import create_app

pytest.importorskip("fastapi")


@pytest.mark.asyncio
async def test_managed_create_read_write_unregister_and_concurrency(
    tmp_path: Path,
    git_repository: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg-data"))
    runtime = await open_web_runtime(tmp_path / "web.sqlite")
    await register_local_repository(
        runtime.store, requested_root=git_repository, display_name="demo"
    )

    created = await create_managed_trusted_policy(
        runtime.store, kind="review", filename="team-review.yaml"
    )
    managed_path = Path(str(created["path"]))
    assert managed_path.parent == managed_policies_root()
    assert managed_path.is_file()  # noqa: ASYNC240

    document = await read_trusted_policy_document(
        runtime.store, kind="review", policy_id=str(created["id"])
    )
    assert document["sha256"] == created["version_sha256"]
    assert "blocking_severities" in document["text"]

    parsed = yaml.safe_load(document["text"])
    assert isinstance(parsed, dict)
    parsed["version"] = "0.1.1"
    updated_text = yaml.safe_dump(parsed, sort_keys=False)
    saved = await write_trusted_policy_document(
        runtime.store,
        kind="review",
        policy_id=str(created["id"]),
        expected_content_sha256=str(document["content_sha256"]),
        text=updated_text,
    )
    assert saved["sha256"] != document["sha256"]
    assert "0.1.1" in saved["text"]

    with pytest.raises(TrustBoundaryError, match="policy_content_changed"):
        await write_trusted_policy_document(
            runtime.store,
            kind="review",
            policy_id=str(created["id"]),
            expected_content_sha256=str(document["content_sha256"]),
            text=updated_text,
        )

    assert await unregister_trusted_policy(
        runtime.store, kind="review", policy_id=str(created["id"])
    )
    assert managed_path.is_file()  # noqa: ASYNC240
    with pytest.raises(TrustBoundaryError, match="unknown policy"):
        await read_trusted_policy_document(
            runtime.store, kind="review", policy_id=str(created["id"])
        )


@pytest.mark.asyncio
async def test_save_after_external_disk_edit_uses_reloaded_disk_sha(
    tmp_path: Path,
    git_repository: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reload-then-save must work when registry sha and disk sha diverge."""

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg-data"))
    runtime = await open_web_runtime(tmp_path / "drift.sqlite")
    await register_local_repository(
        runtime.store, requested_root=git_repository, display_name="demo"
    )
    created = await create_managed_trusted_policy(
        runtime.store, kind="review", filename="drift-review.yaml"
    )
    policy_id = str(created["id"])
    path = Path(str(created["path"]))
    original = await read_trusted_policy_document(runtime.store, kind="review", policy_id=policy_id)
    assert original["sha256"] == original["registered_sha256"]

    parsed = yaml.safe_load(original["text"])
    assert isinstance(parsed, dict)
    parsed["version"] = "0.9.9"
    await asyncio.to_thread(path.write_text, yaml.safe_dump(parsed, sort_keys=False), "utf-8")

    reloaded = await read_trusted_policy_document(runtime.store, kind="review", policy_id=policy_id)
    assert reloaded["sha256"] != reloaded["registered_sha256"]
    assert reloaded["sha256"] != original["sha256"]
    assert reloaded["content_sha256"] != original["content_sha256"]

    parsed["version"] = "0.9.10"
    saved = await write_trusted_policy_document(
        runtime.store,
        kind="review",
        policy_id=policy_id,
        expected_content_sha256=str(reloaded["content_sha256"]),
        text=yaml.safe_dump(parsed, sort_keys=False),
    )
    assert "0.9.10" in saved["text"]
    assert saved["sha256"] == saved["registered_sha256"]


@pytest.mark.asyncio
async def test_comment_only_edit_conflicts_on_raw_content_sha(
    tmp_path: Path,
    git_repository: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Comment/formatting changes must still trip editor optimistic concurrency."""

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg-data"))
    runtime = await open_web_runtime(tmp_path / "comment-race.sqlite")
    await register_local_repository(
        runtime.store, requested_root=git_repository, display_name="demo"
    )
    created = await create_managed_trusted_policy(
        runtime.store, kind="review", filename="comment-race.yaml"
    )
    policy_id = str(created["id"])
    original = await read_trusted_policy_document(runtime.store, kind="review", policy_id=policy_id)
    commented = f"{original['text'].rstrip()}\n# editor-a note\n"
    assert policy_document_content_sha256(commented) != original["content_sha256"]

    saved = await write_trusted_policy_document(
        runtime.store,
        kind="review",
        policy_id=policy_id,
        expected_content_sha256=str(original["content_sha256"]),
        text=commented,
    )
    # Parsed Policy identity is unchanged by a trailing comment.
    assert saved["sha256"] == original["sha256"]
    assert saved["content_sha256"] != original["content_sha256"]

    other_comment = f"{original['text'].rstrip()}\n# editor-b note\n"
    with pytest.raises(TrustBoundaryError, match="policy_content_changed"):
        await write_trusted_policy_document(
            runtime.store,
            kind="review",
            policy_id=policy_id,
            expected_content_sha256=str(original["content_sha256"]),
            text=other_comment,
        )


@pytest.mark.asyncio
async def test_managed_compute_create_matches_provider_and_cleans_failed_bind(
    tmp_path: Path,
    git_repository: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg-data"))
    runtime = await open_web_runtime(tmp_path / "managed-compute.sqlite")
    await register_local_repository(
        runtime.store, requested_root=git_repository, display_name="demo"
    )
    await runtime.store.insert_provider_profile(
        profile_id="profile-openai",
        name="openai",
        provider="openai",
        credential_reference="${OPENAI_API_KEY}",
        endpoint="https://api.openai.com/v1",
    )
    created = await create_managed_trusted_policy(
        runtime.store,
        kind="compute",
        filename="openai-compute.yaml",
        provider_profile_id="profile-openai",
    )
    path = Path(str(created["path"]))
    assert path.is_file()  # noqa: ASYNC240
    assert "provider: openai" in path.read_text(encoding="utf-8")  # noqa: ASYNC240

    await runtime.store.insert_provider_profile(
        profile_id="profile-local",
        name="local",
        provider="local-cli",
        credential_reference=None,
        local_cli_adapter="worktree-json",
        local_cli_command=["/usr/bin/true"],
    )
    local_cli = await create_managed_trusted_policy(
        runtime.store,
        kind="compute",
        filename="local-cli-compute.yaml",
        provider_profile_id="profile-local",
    )
    local_cli_path = Path(str(local_cli["path"]))
    assert "provider: local-cli" in local_cli_path.read_text(encoding="utf-8")  # noqa: ASYNC240

    def _boom(*_args: object, **_kwargs: object) -> None:
        raise TrustBoundaryError("forced bind failure")

    monkeypatch.setattr(policy_registry, "validate_compute_policy_binding", _boom)
    with pytest.raises(TrustBoundaryError, match="forced bind failure"):
        await create_managed_trusted_policy(
            runtime.store,
            kind="compute",
            filename="orphan-compute.yaml",
            provider_profile_id="profile-openai",
        )
    assert not (managed_policies_root() / "orphan-compute.yaml").exists()


@pytest.mark.asyncio
async def test_save_rejects_policy_moved_inside_registered_repository(
    tmp_path: Path,
    git_repository: Path,
    policy_dir: Path,
) -> None:
    runtime = await open_web_runtime(tmp_path / "web.sqlite")
    await register_local_repository(
        runtime.store, requested_root=git_repository, display_name="demo"
    )
    source = policy_dir / "review-policy.yaml"
    registered = await register_trusted_policy(runtime.store, source, kind="review")
    # Relocate the registered path into the repository (simulate trust drift).
    inside = git_repository / "sneaky-policy.yaml"
    inside.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    row = await runtime.store.get_trusted_policy("trusted_review_policies", str(registered["id"]))
    assert row is not None
    # Force the registry path to the in-repo file without going through register.
    await runtime.store.delete_trusted_policy("trusted_review_policies", str(registered["id"]))
    await runtime.store.insert_trusted_policy(
        table="trusted_review_policies",
        policy_id=str(registered["id"]),
        path=str(inside.resolve()),
        version_semver=str(registered["version_semver"]),
        version_sha256=str(registered["version_sha256"]),
    )
    with pytest.raises(TrustBoundaryError, match=r"inside a reviewed repository"):
        await write_trusted_policy_document(
            runtime.store,
            kind="review",
            policy_id=str(registered["id"]),
            expected_content_sha256=str(registered["version_sha256"]),
            text=inside.read_text(encoding="utf-8"),
        )


@pytest.mark.asyncio
async def test_http_policy_document_endpoints(
    tmp_path: Path,
    git_repository: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi.testclient import TestClient

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg-data"))
    runtime = await open_web_runtime(tmp_path / "http.sqlite")
    runtime.csrf_token = "test-csrf"
    await register_local_repository(
        runtime.store, requested_root=git_repository, display_name="demo"
    )
    application = create_app(web_runtime=runtime, enable_local_web=False, serve_frontend=False)
    headers = {"X-CSRF-Token": "test-csrf", "Origin": "http://127.0.0.1"}
    with TestClient(application, base_url="http://127.0.0.1") as client:
        created = client.post(
            "/api/v1/review-policies/create-managed",
            headers=headers,
            json={"filename": "from-http.yaml"},
        )
        assert created.status_code == 201, created.text
        policy_id = created.json()["policy_id"]

        document = client.get(f"/api/v1/review-policies/{policy_id}/document")
        assert document.status_code == 200
        body = document.json()
        assert body["policy_id"] == policy_id
        assert body["sha256"]
        assert body["content_sha256"]

        parsed = yaml.safe_load(body["text"])
        parsed["version"] = "0.2.0"
        saved = client.put(
            f"/api/v1/review-policies/{policy_id}/document",
            headers=headers,
            json={
                "expected_content_sha256": body["content_sha256"],
                "text": yaml.safe_dump(parsed),
            },
        )
        assert saved.status_code == 200, saved.text
        assert saved.json()["sha256"] != body["sha256"]
        assert saved.json()["content_sha256"] != body["content_sha256"]

        conflict = client.put(
            f"/api/v1/review-policies/{policy_id}/document",
            headers=headers,
            json={
                "expected_content_sha256": body["content_sha256"],
                "text": yaml.safe_dump(parsed),
            },
        )
        assert conflict.status_code == 409
        assert conflict.json()["error"]["code"] == "policy_content_changed"

        path_on_disk = Path(body["path"])
        deleted = client.delete(f"/api/v1/review-policies/{policy_id}", headers=headers)
        assert deleted.status_code == 204
        assert path_on_disk.is_file()  # noqa: ASYNC240
        missing = client.get(f"/api/v1/review-policies/{policy_id}/document")
        assert missing.status_code == 404


@pytest.mark.asyncio
async def test_concurrent_managed_create_same_name_keeps_winner_file(
    tmp_path: Path,
    git_repository: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two same-name creates: exactly one wins; loser must not delete the winner."""

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg-data"))
    runtime = await open_web_runtime(tmp_path / "race-create.sqlite")
    await register_local_repository(
        runtime.store, requested_root=git_repository, display_name="demo"
    )

    async def _attempt() -> str:
        try:
            created = await create_managed_trusted_policy(
                runtime.store, kind="review", filename="race.yaml"
            )
            return f"ok:{created['id']}"
        except TrustBoundaryError as exc:
            return f"err:{exc}"

    first, second = await asyncio.gather(_attempt(), _attempt())
    outcomes = {first, second}
    assert sum(1 for item in outcomes if item.startswith("ok:")) == 1
    assert sum(1 for item in outcomes if item.startswith("err:")) == 1
    target = managed_policies_root() / "race.yaml"
    assert target.is_file()
    winner_id = next(item.split(":", 1)[1] for item in outcomes if item.startswith("ok:"))
    document = await read_trusted_policy_document(runtime.store, kind="review", policy_id=winner_id)
    assert Path(str(document["path"])) == target


@pytest.mark.asyncio
async def test_concurrent_saves_second_observes_conflict(
    tmp_path: Path,
    git_repository: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Interleaved saves that share the same expected sha: one commits, one 409s."""

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg-data"))
    runtime = await open_web_runtime(tmp_path / "race-save.sqlite")
    await register_local_repository(
        runtime.store, requested_root=git_repository, display_name="demo"
    )
    created = await create_managed_trusted_policy(
        runtime.store, kind="review", filename="race-save.yaml"
    )
    policy_id = str(created["id"])
    document = await read_trusted_policy_document(runtime.store, kind="review", policy_id=policy_id)
    base = yaml.safe_load(document["text"])
    assert isinstance(base, dict)
    text_a = yaml.safe_dump({**base, "version": "0.2.0"}, sort_keys=False)
    text_b = yaml.safe_dump({**base, "version": "0.3.0"}, sort_keys=False)
    expected = str(document["content_sha256"])

    async def _save(text: str) -> str:
        try:
            saved = await write_trusted_policy_document(
                runtime.store,
                kind="review",
                policy_id=policy_id,
                expected_content_sha256=expected,
                text=text,
            )
            return f"ok:{saved['sha256']}"
        except TrustBoundaryError as exc:
            return f"err:{exc}"

    first, second = await asyncio.gather(_save(text_a), _save(text_b))
    outcomes = [first, second]
    assert sum(1 for item in outcomes if item.startswith("ok:")) == 1
    assert sum(1 for item in outcomes if item.startswith("err:")) == 1
    assert any("policy_content_changed" in item for item in outcomes if item.startswith("err:"))
    final = await read_trusted_policy_document(runtime.store, kind="review", policy_id=policy_id)
    assert final["sha256"] == final["registered_sha256"]
    parsed = yaml.safe_load(final["text"])
    assert isinstance(parsed, dict)
    assert parsed["version"] in {"0.2.0", "0.3.0"}


@pytest.mark.asyncio
async def test_save_holds_lock_through_registry_identity_update(
    tmp_path: Path,
    git_repository: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Registry identity update stays inside the exclusive file lock."""

    import threading

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg-data"))
    runtime = await open_web_runtime(tmp_path / "race-lock-registry.sqlite")
    await register_local_repository(
        runtime.store, requested_root=git_repository, display_name="demo"
    )
    created = await create_managed_trusted_policy(
        runtime.store, kind="review", filename="lock-registry.yaml"
    )
    policy_id = str(created["id"])
    document = await read_trusted_policy_document(runtime.store, kind="review", policy_id=policy_id)
    base = yaml.safe_load(document["text"])
    assert isinstance(base, dict)
    text_a = yaml.safe_dump({**base, "version": "0.2.0"}, sort_keys=False)
    text_b = yaml.safe_dump({**base, "version": "0.3.0"}, sort_keys=False)
    expected = str(document["content_sha256"])

    entered_registry = threading.Event()
    release_registry = threading.Event()
    real_sync = runtime.store.update_trusted_policy_identity_sync

    def _delayed_sync(**kwargs: object) -> bool:
        entered_registry.set()
        assert release_registry.wait(timeout=5.0)
        return real_sync(**kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(runtime.store, "update_trusted_policy_identity_sync", _delayed_sync)

    async def _save(text: str) -> str:
        try:
            saved = await write_trusted_policy_document(
                runtime.store,
                kind="review",
                policy_id=policy_id,
                expected_content_sha256=expected,
                text=text,
            )
            return f"ok:{saved['sha256']}"
        except TrustBoundaryError as exc:
            return f"err:{exc}"

    first_task = asyncio.create_task(_save(text_a))
    assert await asyncio.to_thread(entered_registry.wait, 5.0)
    second_task = asyncio.create_task(_save(text_b))
    # While A still holds the lock inside registry update, B must not finish.
    await asyncio.sleep(0.1)
    assert not second_task.done()
    release_registry.set()
    first, second = await asyncio.gather(first_task, second_task)
    outcomes = [first, second]
    assert sum(1 for item in outcomes if item.startswith("ok:")) == 1
    assert sum(1 for item in outcomes if item.startswith("err:")) == 1
    final = await read_trusted_policy_document(runtime.store, kind="review", policy_id=policy_id)
    assert final["sha256"] == final["registered_sha256"]


@pytest.mark.asyncio
async def test_read_pairs_text_with_matching_sha_under_concurrent_save(
    tmp_path: Path,
    git_repository: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GET text always pairs with matching identity and content digests."""

    import hashlib

    import yaml as yaml_mod

    from worktree_review.core.policy import canonical_policy_bytes

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg-data"))
    runtime = await open_web_runtime(tmp_path / "race-read.sqlite")
    await register_local_repository(
        runtime.store, requested_root=git_repository, display_name="demo"
    )
    created = await create_managed_trusted_policy(
        runtime.store, kind="review", filename="race-read.yaml"
    )
    policy_id = str(created["id"])
    document = await read_trusted_policy_document(runtime.store, kind="review", policy_id=policy_id)
    base = yaml.safe_load(document["text"])
    assert isinstance(base, dict)

    def _identity_sha_of_text(text: str) -> str:
        parsed = yaml_mod.safe_load(text)
        assert isinstance(parsed, dict)
        return hashlib.sha256(canonical_policy_bytes(parsed)).hexdigest()

    stop = asyncio.Event()
    mismatches: list[tuple[str, str, str]] = []

    async def _reader() -> None:
        while not stop.is_set():
            loaded = await read_trusted_policy_document(
                runtime.store, kind="review", policy_id=policy_id
            )
            text = str(loaded["text"])
            identity_digest = _identity_sha_of_text(text)
            content_digest = policy_document_content_sha256(text)
            if identity_digest != loaded["sha256"] or content_digest != loaded["content_sha256"]:
                mismatches.append(
                    (identity_digest, str(loaded["sha256"]), str(loaded["content_sha256"]))
                )
            await asyncio.sleep(0)

    async def _writer() -> None:
        for index in range(30):
            current = await read_trusted_policy_document(
                runtime.store, kind="review", policy_id=policy_id
            )
            parsed = yaml.safe_load(current["text"])
            assert isinstance(parsed, dict)
            parsed["version"] = f"0.1.{index}"
            try:
                await write_trusted_policy_document(
                    runtime.store,
                    kind="review",
                    policy_id=policy_id,
                    expected_content_sha256=str(current["content_sha256"]),
                    text=yaml.safe_dump(parsed, sort_keys=False),
                )
            except TrustBoundaryError:
                continue

    reader_task = asyncio.create_task(_reader())
    await _writer()
    stop.set()
    await reader_task
    assert mismatches == []
