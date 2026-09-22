"""Provider Profile persistence, Compute Policy binding, and frozen Attempt config."""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path

import pytest

from worktree_review.core.provider import ScriptedProvider
from worktree_review.platform.web.provider_resolution import (
    parse_frozen_provider_snapshot,
    resolve_frozen_provider_configuration,
)
from worktree_review.platform.web.registry import (
    TrustBoundaryError,
    register_local_repository,
    register_trusted_policy,
)
from worktree_review.platform.web.runtime import open_web_runtime
from worktree_review.platform.web.worker import execute_attempt
from worktree_review.server.app import create_app

pytest.importorskip("fastapi")

LOCAL_CLI_MODEL = "fixture-reviewer"


def _local_cli_command(script: Path) -> tuple[str, ...]:
    return (sys.executable, str(script))


def _git_init_quiet(container: Path) -> None:
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=container, check=True)


def _local_cli_user_config_yaml(command: tuple[str, ...]) -> str:
    # local-cli lives in the derived user-config path by Core design; advanced
    # compute-policy files refuse local-cli (the fingerprint and consent text
    # are generated here, never hand-written).
    argv = ", ".join(json.dumps(argument) for argument in command)
    return f"""\
schema: worktree-review.config/v1
version: 0.1.0
provider: local-cli
command: [{argv}]
model: {LOCAL_CLI_MODEL}
"""


@pytest.fixture
def reviewer_script(tmp_path: Path) -> Path:
    script = tmp_path / "fixture-reviewer.py"
    script.write_text(
        "import json, sys\n"
        "request = json.load(sys.stdin)\n"
        "payloads = json.loads((\n"
        "    open(sys.argv[1], encoding='utf-8').read()\n"
        ") if len(sys.argv) > 1 else '{}')\n"
        "json.dump(payloads.get(request['dimension_id'], {'findings': []}), sys.stdout)\n",
        encoding="utf-8",
    )
    return script


async def _bound_setup(
    tmp_path: Path,
    git_repository: Path,
    policy_dir: Path,
    *,
    reviewer_script: Path | None = None,
):
    """Runtime with a registered repo plus a bound Review/Compute Policy pair."""

    runtime = await open_web_runtime(tmp_path / "binding.sqlite")
    runtime.csrf_token = "test-csrf"
    repository = await register_local_repository(
        runtime.store, requested_root=git_repository, display_name="demo"
    )
    review = await register_trusted_policy(
        runtime.store, policy_dir / "review-policy.yaml", kind="review"
    )
    if reviewer_script is not None:
        command = _local_cli_command(reviewer_script)
        compute_path = tmp_path / "trusted-policy" / "config-local-cli.yaml"
        compute_path.write_text(_local_cli_user_config_yaml(command), encoding="utf-8")
        profile = {
            "profile_id": "profile-local-cli",
            "name": "fixture-local-cli",
            "provider": "local-cli",
            "credential_reference": None,
            "endpoint": None,
            "local_cli_adapter": "worktree-json",
            "local_cli_command": list(command),
            "adapter_label": "fixture reviewer",
        }
    else:
        compute_path = policy_dir / "compute-policy.yaml"
        profile = {
            "profile_id": "profile-remote",
            "name": "fixture-anthropic",
            "provider": "anthropic",
            "credential_reference": "${ANTHROPIC_API_KEY}",
            "endpoint": "https://api.anthropic.com",
            "local_cli_adapter": None,
            "local_cli_command": None,
            "adapter_label": None,
        }
    await runtime.store.insert_provider_profile(**profile)
    compute = await register_trusted_policy(
        runtime.store,
        compute_path,
        kind="compute",
        provider_profile_id=str(profile["profile_id"]),
    )
    return runtime, repository, review, compute


def _create_body(
    repository: dict[str, str], review: dict[str, str], compute: dict[str, str]
) -> dict[str, object]:
    return {
        "repository_id": repository["id"],
        "source": {"kind": "local-worktree", "target_ref": "main"},
        "review_policy_id": review["id"],
        "compute_policy_id": compute["id"],
    }


def _headers(idempotency: str) -> dict[str, str]:
    return {
        "X-CSRF-Token": "test-csrf",
        "Origin": "http://127.0.0.1",
        "Idempotency-Key": idempotency,
    }


@pytest.mark.asyncio
async def test_local_cli_profile_fields_round_trip_through_api(
    tmp_path: Path, git_repository: Path, policy_dir: Path
) -> None:
    from fastapi.testclient import TestClient

    runtime = await open_web_runtime(tmp_path / "profiles.sqlite")
    runtime.csrf_token = "test-csrf"
    application = create_app(web_runtime=runtime, enable_local_web=False)
    with TestClient(application, base_url="http://127.0.0.1") as client:
        created = client.post(
            "/api/v1/provider-profiles",
            json={
                "name": "codex-local",
                "provider": "local-cli",
                "local_cli_adapter": "worktree-json",
                "local_cli_command": ["codex", "exec", "--json"],
                "adapter_label": "Codex CLI",
            },
            headers=_headers("p1"),
        )
        assert created.status_code == 201, created.text
        body = created.json()
        assert body["local_cli_adapter"] == "worktree-json"
        assert body["local_cli_command"] == ["codex", "exec", "--json"]
        assert body["adapter_label"] == "Codex CLI"
        assert body["credential_state"] == "not_applicable"

        listed = client.get("/api/v1/provider-profiles")
        assert listed.json()[0]["local_cli_command"] == ["codex", "exec", "--json"]

        updated = client.patch(
            f"/api/v1/provider-profiles/{body['profile_id']}",
            json={
                "name": "codex-local",
                "provider": "local-cli",
                "local_cli_adapter": "prompt-json",
                "local_cli_command": ["codex", "exec"],
                "adapter_label": None,
            },
            headers=_headers("p2"),
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["local_cli_adapter"] == "prompt-json"
        assert updated.json()["local_cli_command"] == ["codex", "exec"]


@pytest.mark.asyncio
async def test_profile_shape_validation_rejects_mixed_kinds(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    runtime = await open_web_runtime(tmp_path / "profiles-shape.sqlite")
    runtime.csrf_token = "test-csrf"
    application = create_app(web_runtime=runtime, enable_local_web=False)
    with TestClient(application, base_url="http://127.0.0.1") as client:
        remote_without_credential = client.post(
            "/api/v1/provider-profiles",
            json={"name": "bad", "provider": "anthropic"},
            headers=_headers("s1"),
        )
        assert remote_without_credential.status_code == 400
        plain_http_endpoint = client.post(
            "/api/v1/provider-profiles",
            json={
                "name": "bad",
                "provider": "openai",
                "endpoint": "http://api.openai.com",
                "credential_reference": "${OPENAI_API_KEY}",
            },
            headers=_headers("s2"),
        )
        assert plain_http_endpoint.status_code == 400
        local_without_command = client.post(
            "/api/v1/provider-profiles",
            json={"name": "bad", "provider": "local-cli", "local_cli_adapter": "worktree-json"},
            headers=_headers("s3"),
        )
        assert local_without_command.status_code == 400


@pytest.mark.asyncio
async def test_compute_policy_binding_is_persisted_and_presented(
    tmp_path: Path, git_repository: Path, policy_dir: Path
) -> None:
    from fastapi.testclient import TestClient

    runtime, _repository, _review, compute = await _bound_setup(
        tmp_path, git_repository, policy_dir
    )
    application = create_app(web_runtime=runtime, enable_local_web=False)
    with TestClient(application, base_url="http://127.0.0.1") as client:
        listed = client.get("/api/v1/compute-policies")
        entry = listed.json()[0]
        assert entry["policy_id"] == compute["id"]
        assert entry["provider_profile_id"] == "profile-remote"
        assert entry["provider_profile_name"] == "fixture-anthropic"


@pytest.mark.asyncio
async def test_compute_policy_binding_rejects_mismatched_profile(
    tmp_path: Path, git_repository: Path, policy_dir: Path
) -> None:
    runtime = await open_web_runtime(tmp_path / "mismatch.sqlite")
    await runtime.store.insert_provider_profile(
        profile_id="profile-openai",
        name="openai",
        provider="openai",
        credential_reference="${OPENAI_API_KEY}",
    )
    with pytest.raises(TrustBoundaryError, match="does not match"):
        await register_trusted_policy(
            runtime.store,
            policy_dir / "compute-policy.yaml",
            kind="compute",
            provider_profile_id="profile-openai",
        )


@pytest.mark.asyncio
async def test_create_review_requires_bound_provider_profile(
    tmp_path: Path, git_repository: Path, policy_dir: Path
) -> None:
    from fastapi.testclient import TestClient

    runtime = await open_web_runtime(tmp_path / "unbound.sqlite")
    runtime.csrf_token = "test-csrf"
    repository = await register_local_repository(
        runtime.store, requested_root=git_repository, display_name="demo"
    )
    review = await register_trusted_policy(
        runtime.store, policy_dir / "review-policy.yaml", kind="review"
    )
    compute = await register_trusted_policy(
        runtime.store, policy_dir / "compute-policy.yaml", kind="compute"
    )
    application = create_app(web_runtime=runtime, enable_local_web=False)
    with TestClient(application, base_url="http://127.0.0.1") as client:
        created = client.post(
            "/api/v1/reviews",
            json=_create_body(repository, review, compute),
            headers=_headers("u1"),
        )
        assert created.status_code == 409
        assert created.json()["error"]["code"] == "compute_policy_unbound"


@pytest.mark.asyncio
async def test_attempt_freezes_provider_and_ignores_later_profile_edits(
    tmp_path: Path,
    git_repository: Path,
    policy_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi.testclient import TestClient

    monkeypatch.setenv("ANTHROPIC_API_KEY", "frozen-key")
    runtime, repository, review, compute = await _bound_setup(tmp_path, git_repository, policy_dir)
    captured: list[tuple[str | None, str | None]] = []

    def _factory(_policy: object, configuration: object) -> ScriptedProvider:
        url = getattr(configuration, "url", None)
        key = getattr(configuration, "api_key", None)
        captured.append((url, None if key is None else key.get_secret_value()))
        return ScriptedProvider(payloads={"correctness": {"findings": []}})

    runtime.provider_factory = _factory
    application = create_app(web_runtime=runtime, enable_local_web=False)
    with TestClient(application, base_url="http://127.0.0.1") as client:
        created = client.post(
            "/api/v1/reviews",
            json=_create_body(repository, review, compute),
            headers=_headers("f1"),
        )
        assert created.status_code == 202, created.text
        attempt_id = created.json()["attempt_id"]
        # Configuration drift AFTER the Attempt was created must not leak in.
        await runtime.store.update_provider_profile(
            profile_id="profile-remote",
            name="fixture-anthropic",
            provider="anthropic",
            credential_reference="${ANTHROPIC_API_KEY}",
            endpoint="https://attacker.invalid",
        )
    await execute_attempt(runtime, attempt_id)
    assert captured == [("https://api.anthropic.com", "frozen-key")]
    run = await runtime.store.get_run(attempt_id)
    assert run is not None and run.result_json is not None


@pytest.mark.asyncio
async def test_missing_credential_fails_attempt_with_safe_event(
    tmp_path: Path, git_repository: Path, policy_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from fastapi.testclient import TestClient

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    runtime, repository, review, compute = await _bound_setup(tmp_path, git_repository, policy_dir)
    application = create_app(web_runtime=runtime, enable_local_web=False)
    with TestClient(application, base_url="http://127.0.0.1") as client:
        created = client.post(
            "/api/v1/reviews",
            json=_create_body(repository, review, compute),
            headers=_headers("m1"),
        )
        attempt_id = created.json()["attempt_id"]
    await execute_attempt(runtime, attempt_id)
    run = await runtime.store.get_run(attempt_id)
    assert run is not None
    assert run.run_status.value == "failed"
    events = await runtime.store.list_events(attempt_id)
    assert events[-1].event_type == "attempt.failed"
    assert "ANTHROPIC_API_KEY" in str(events[-1].payload["safe_detail"])


@pytest.mark.asyncio
async def test_local_cli_argv_reaches_provider_without_shell(
    tmp_path: Path,
    git_repository: Path,
    policy_dir: Path,
    reviewer_script: Path,
) -> None:
    """End to end through the real LocalCliProvider: argv, no shell, real subprocess."""
    from fastapi.testclient import TestClient

    runtime, repository, review, compute = await _bound_setup(
        tmp_path, git_repository, policy_dir, reviewer_script=reviewer_script
    )
    application = create_app(web_runtime=runtime, enable_local_web=False)
    with TestClient(application, base_url="http://127.0.0.1") as client:
        created = client.post(
            "/api/v1/reviews",
            json=_create_body(repository, review, compute),
            headers=_headers("l1"),
        )
        assert created.status_code == 202, created.text
        attempt_id = created.json()["attempt_id"]
    await execute_attempt(runtime, attempt_id)
    run = await runtime.store.get_run(attempt_id)
    assert run is not None
    assert run.run_status.value == "completed"
    report = json.loads(run.result_json or "{}")
    assert report["gate_state"] == "Passed"


@pytest.mark.asyncio
async def test_provider_construction_failure_isolated_per_attempt(
    tmp_path: Path,
    git_repository: Path,
    policy_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Blocker 5: the first Attempt's provider failure must not kill the second."""
    from fastapi.testclient import TestClient

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    runtime, repository, review, compute = await _bound_setup(tmp_path, git_repository, policy_dir)
    calls = 0

    def _flaky_factory(_policy: object, _config: object) -> ScriptedProvider:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("provider construction exploded")
        return ScriptedProvider(payloads={"correctness": {"findings": []}})

    runtime.provider_factory = _flaky_factory
    application = create_app(web_runtime=runtime, enable_local_web=False)
    attempt_ids: list[str] = []
    with TestClient(application, base_url="http://127.0.0.1") as client:
        for index in range(2):
            created = client.post(
                "/api/v1/reviews",
                json=_create_body(repository, review, compute),
                headers=_headers(f"b{index}"),
            )
            attempt_ids.append(created.json()["attempt_id"])

    async def _consume() -> None:
        while True:
            queued = await asyncio.wait_for(runtime.queue.get(), timeout=5)
            await execute_attempt(runtime, queued)
            if runtime.queue.empty():
                return

    await _consume()
    first = await runtime.store.get_run(attempt_ids[0])
    second = await runtime.store.get_run(attempt_ids[1])
    assert first is not None and first.run_status.value == "failed"
    first_events = await runtime.store.list_events(attempt_ids[0])
    assert first_events[-1].event_type == "attempt.failed"
    # RuntimeError is an internal error: the payload is typed and fixed-text,
    # never the arbitrary exception message.
    assert first_events[-1].payload["category"] == "internal"
    assert first_events[-1].payload["safe_detail"] == "internal error; see server logs"
    assert second is not None and second.run_status.value == "completed"
    assert second.result_json is not None


def test_resolve_frozen_provider_rejects_drifted_local_cli(policy_dir: Path) -> None:
    from worktree_review.core.policy import load_compute_policy

    command = ("fixture-reviewer",)
    yaml_path = policy_dir / "compute-policy.yaml"
    compute_policy = load_compute_policy(yaml_path)[0]
    assert compute_policy.provider == "anthropic"
    frozen = json.dumps(
        {
            "schema": "worktree-review.frozen-provider/v1",
            "profile_id": "p",
            "provider": "local-cli",
            "local_cli_adapter": "worktree-json",
            "local_cli_command": list(command),
            "credential_reference": None,
            "endpoint": None,
            "adapter_label": None,
        }
    )
    with pytest.raises(Exception, match="does not match"):
        resolve_frozen_provider_configuration(frozen, compute_policy=compute_policy)


def test_frozen_snapshot_round_trip() -> None:
    frozen = json.dumps(
        {
            "schema": "worktree-review.frozen-provider/v1",
            "profile_id": "p1",
            "profile_name": "name",
            "provider": "anthropic",
            "endpoint": None,
            "local_cli_adapter": None,
            "local_cli_command": [],
            "adapter_label": None,
            "credential_reference": "${ANTHROPIC_API_KEY}",
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    parsed = parse_frozen_provider_snapshot(frozen)
    assert parsed["profile_id"] == "p1"


@pytest.mark.asyncio
async def test_trusted_policy_drift_after_registration_fails_closed(
    tmp_path: Path, git_repository: Path, policy_dir: Path
) -> None:
    """A trusted policy file edited after registration must not change the Gate."""
    from fastapi.testclient import TestClient

    runtime, repository, review, compute = await _bound_setup(tmp_path, git_repository, policy_dir)
    runtime.provider_factory = lambda _policy, _config: ScriptedProvider(
        payloads={"correctness": {"findings": []}}
    )
    application = create_app(web_runtime=runtime, enable_local_web=False)
    with TestClient(application, base_url="http://127.0.0.1") as client:
        created = client.post(
            "/api/v1/reviews",
            json=_create_body(repository, review, compute),
            headers=_headers("d1"),
        )
        attempt_id = created.json()["attempt_id"]
        # Drift the trusted review policy AFTER the Attempt exists.
        policy_path = policy_dir / "review-policy.yaml"
        # Semantic tampering: weakening blocking severities must be detected
        # (comments alone do not change the canonical policy identity).
        policy_path.write_text(
            policy_path.read_text(encoding="utf-8").replace("  - major\n", ""),
            encoding="utf-8",
        )
        drifted_listing = client.get("/api/v1/review-policies").json()
        drifted = next(item for item in drifted_listing if item["policy_id"] == review["id"])
        assert drifted["drifted"] is True
        assert drifted_listing[0]["builtin"] is True
    await execute_attempt(runtime, attempt_id)
    run = await runtime.store.get_run(attempt_id)
    assert run is not None
    assert run.run_status.value == "failed"
    events = await runtime.store.list_events(attempt_id)
    assert events[-1].event_type == "attempt.failed"
    assert "drifted" in str(events[-1].payload["safe_detail"])


@pytest.mark.asyncio
async def test_binding_revalidated_at_creation_when_profile_edited(
    tmp_path: Path, git_repository: Path, policy_dir: Path
) -> None:
    """A profile edited to another provider after registration is rejected at creation."""
    from fastapi.testclient import TestClient

    runtime, repository, review, compute = await _bound_setup(tmp_path, git_repository, policy_dir)
    await runtime.store.update_provider_profile(
        profile_id="profile-remote",
        name="fixture-anthropic",
        provider="openai",
        credential_reference="${OPENAI_API_KEY}",
        endpoint=None,
    )
    application = create_app(web_runtime=runtime, enable_local_web=False)
    with TestClient(application, base_url="http://127.0.0.1") as client:
        created = client.post(
            "/api/v1/reviews",
            json=_create_body(repository, review, compute),
            headers=_headers("e1"),
        )
        assert created.status_code == 409
        assert created.json()["error"]["code"] == "provider_profile_binding_drifted"


@pytest.mark.asyncio
async def test_repository_registration_rejects_swallowing_a_trusted_policy(
    tmp_path: Path, git_repository: Path, policy_dir: Path
) -> None:
    """Registering the policy first must not allow registering its parent repo after."""
    runtime = await open_web_runtime(tmp_path / "trust.sqlite")
    container = tmp_path / "container-repo"
    (container / "policies").mkdir(parents=True)
    (container / "policies" / "review-policy.yaml").write_text(
        (policy_dir / "review-policy.yaml").read_text(encoding="utf-8"), encoding="utf-8"
    )
    await asyncio.to_thread(_git_init_quiet, container)
    trusted = await register_trusted_policy(
        runtime.store, container / "policies" / "review-policy.yaml", kind="review"
    )
    assert trusted["id"]
    # Now swallowing that policy with a repository registration must fail.
    with pytest.raises(TrustBoundaryError, match="already-registered trusted policy"):
        await register_local_repository(
            runtime.store, requested_root=container, display_name="swallow"
        )
