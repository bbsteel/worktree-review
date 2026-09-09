from __future__ import annotations

from pathlib import Path

import pytest

from worktree_review.core.config import load_user_configuration
from worktree_review.core.errors import PolicyValidationError


def test_minimal_remote_configuration_derives_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(
        "provider: anthropic\nurl: https://example.invalid/v1\nkey: ${TEST_PROVIDER_KEY}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("TEST_PROVIDER_KEY", "secret-value")

    compute_policy, version, provider_configuration = load_user_configuration(path)

    assert compute_policy.provider == "anthropic"
    assert compute_policy.model == "claude-sonnet-4-5"
    assert compute_policy.max_budget_usd is None
    assert compute_policy.max_output_tokens_per_call == 4096
    assert compute_policy.permit_remote_transmission is True
    assert compute_policy.data_destination == "https://example.invalid/v1"
    assert provider_configuration.api_key is not None
    assert provider_configuration.api_key.get_secret_value() == "secret-value"
    assert len(version.sha256) == 64


def test_provider_key_is_not_part_of_compute_policy_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(
        "provider: anthropic\nurl: https://example.invalid\nkey: ${TEST_PROVIDER_KEY}\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("TEST_PROVIDER_KEY", "first-secret")
    _first_policy, first_version, _first_provider = load_user_configuration(path)
    monkeypatch.setenv("TEST_PROVIDER_KEY", "second-secret")
    _second_policy, second_version, _second_provider = load_user_configuration(path)

    assert first_version == second_version


def test_missing_referenced_provider_key_fails_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(
        "provider: openai\nurl: https://example.invalid/v1\nkey: ${MISSING_KEY}\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("MISSING_KEY", raising=False)

    with pytest.raises(PolicyValidationError, match="MISSING_KEY"):
        load_user_configuration(path)


def test_normal_configuration_rejects_advanced_compute_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(
        "provider: anthropic\nkey: ${TEST_PROVIDER_KEY}\nmax_budget_usd: 2\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("TEST_PROVIDER_KEY", "secret-value")

    with pytest.raises(PolicyValidationError, match=r"user-config\.v1"):
        load_user_configuration(path)


def test_standard_remote_url_is_optional(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(
        "provider: openai\nkey: ${TEST_PROVIDER_KEY}\nmodel: gpt-test\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("TEST_PROVIDER_KEY", "secret-value")

    compute_policy, _version, provider_configuration = load_user_configuration(path)

    assert compute_policy.data_destination == "https://api.openai.com/v1"
    assert provider_configuration.url == "https://api.openai.com/v1"


def test_local_cli_configuration_discloses_command_handoff(
    tmp_path: Path,
) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(
        "provider: local-cli\ncommand:\n  - review-provider\n",
        encoding="utf-8",
    )

    compute_policy, _version, provider_configuration = load_user_configuration(path)

    assert compute_policy.provider == "local-cli"
    assert compute_policy.permit_remote_transmission is True
    assert compute_policy.data_destination == (
        "Configured local command; downstream destination is command-defined."
    )
    assert compute_policy.known_retention == (
        "Command/provider-defined; inspect the command and provider account terms."
    )
    assert compute_policy.provider_configuration_fingerprint is not None
    assert provider_configuration.command == ("review-provider",)
    assert provider_configuration.configuration_fingerprint == (
        compute_policy.provider_configuration_fingerprint
    )


def test_local_command_configuration_changes_compute_policy_identity(tmp_path: Path) -> None:
    first_path = tmp_path / "first.yaml"
    second_path = tmp_path / "second.yaml"
    first_path.write_text(
        "provider: local-cli\ncommand:\n  - review-provider\n  - --safe\n",
        encoding="utf-8",
    )
    second_path.write_text(
        "provider: local-cli\ncommand:\n  - review-provider\n  - --unsafe\n",
        encoding="utf-8",
    )

    first_policy, first_version, _first_provider = load_user_configuration(first_path)
    second_policy, second_version, _second_provider = load_user_configuration(second_path)

    assert first_policy.provider_configuration_fingerprint != (
        second_policy.provider_configuration_fingerprint
    )
    assert first_version != second_version


def test_repository_config_example_is_a_loadable_minimal_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository_root = Path(__file__).resolve().parents[2]
    monkeypatch.setenv("ANTHROPIC_API_KEY", "example-secret")

    compute_policy, _version, provider_configuration = load_user_configuration(
        repository_root / "config.example.yaml"
    )

    assert compute_policy.provider == "anthropic"
    assert compute_policy.model == "claude-sonnet-4-5"
    assert provider_configuration.url == "https://api.anthropic.com"
