from __future__ import annotations

from pathlib import Path

import pytest

from worktree_review.core.errors import PolicyValidationError
from worktree_review.core.policy import (
    load_builtin_review_policy,
    load_compute_policy,
    load_review_policy,
    policy_version_identity,
)


def test_load_review_policy(policy_dir: Path) -> None:
    policy, identity = load_review_policy(policy_dir / "review-policy.yaml")
    assert policy.required_dimensions == ("correctness",)
    assert identity.semver == "0.1.0"
    assert len(identity.sha256) == 64
    assert policy.context.optional_globs == ("AGENTS.md", "CLAUDE.md")


def test_builtin_review_policy_is_available_without_a_file() -> None:
    policy, identity = load_builtin_review_policy()

    assert policy.required_dimensions == ("correctness", "security")
    assert policy.blocking_severities == ("critical", "major")
    assert policy.context.optional_globs == ("AGENTS.md", "CLAUDE.md")
    assert identity.semver == "0.1.0"
    assert len(identity.sha256) == 64


def test_policy_hash_is_stable_across_key_order(tmp_path: Path) -> None:
    first = {
        "schema": "worktree-review.review-policy/v1",
        "version": "1.2.3",
        "required_dimensions": ["a", "b"],
    }
    second = {
        "required_dimensions": ["a", "b"],
        "version": "1.2.3",
        "schema": "worktree-review.review-policy/v1",
    }
    assert policy_version_identity(first, "1.2.3") == policy_version_identity(second, "1.2.3")


def test_invalid_review_policy_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text("schema: nope\nversion: 1.0.0\n", encoding="utf-8")
    with pytest.raises(PolicyValidationError):
        load_review_policy(path)


def test_load_compute_policy(policy_dir: Path) -> None:
    policy, identity = load_compute_policy(policy_dir / "compute-policy.yaml")
    assert policy.provider == "anthropic"
    assert identity.semver == "0.1.0"
    assert policy.max_output_tokens_per_call == 8192


def test_advanced_compute_policy_rejects_local_cli(tmp_path: Path) -> None:
    path = tmp_path / "local-compute.yaml"
    path.write_text(
        "schema: worktree-review.compute-policy/v1\n"
        "version: 1.0.0\n"
        "provider: local-cli\n"
        "model: review-provider\n"
        "max_budget_usd: 1\n"
        "data_destination: local command\n"
        "known_retention: command-defined\n",
        encoding="utf-8",
    )

    with pytest.raises(PolicyValidationError, match="local-cli"):
        load_compute_policy(path)


def test_example_policies_validate() -> None:
    root = Path(__file__).resolve().parents[2]
    review_policy, _review_identity = load_review_policy(root / "examples" / "review-policy.yaml")
    compute_policy, _compute_identity = load_compute_policy(
        root / "examples" / "compute-policy.yaml"
    )
    assert "correctness" in review_policy.required_dimensions
    assert compute_policy.provider == "anthropic"
    assert "AGENTS.md" in review_policy.context.optional_globs
