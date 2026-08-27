from __future__ import annotations

from decimal import Decimal

import pytest

from worktree_review.core.policy import ComputePolicy
from worktree_review.core.provider import (
    BudgetDecision,
    ScriptedProvider,
    UsageKind,
    UsageRecord,
    apply_input_price,
    apply_usage_price,
    preflight_budget,
)


def _compute_policy(**overrides: object) -> ComputePolicy:
    payload: dict[str, object] = {
        "schema": "worktree-review.compute-policy/v1",
        "version": "1.0.0",
        "provider": "anthropic",
        "model": "claude-sonnet-4-5",
        "max_budget_usd": 1,
        "allow_start_under_uncertain_price": False,
        "data_destination": "https://api.anthropic.com",
        "known_retention": "test",
    }
    payload.update(overrides)
    return ComputePolicy.model_validate(payload)


def test_preflight_refuses_when_cost_exceeds_budget() -> None:
    policy = _compute_policy(max_budget_usd=1, input_usd_per_million_tokens=3)
    estimated = apply_input_price(
        UsageRecord(
            kind=UsageKind.ESTIMATED,
            input_tokens=1_000_000,
            provider="anthropic",
            model="x",
        ),
        policy,
    )
    assert estimated.cost_usd == Decimal("3")
    assert preflight_budget(policy, estimated) is BudgetDecision.REFUSE


def test_usage_price_includes_output_tokens() -> None:
    policy = _compute_policy(input_usd_per_million_tokens=3, output_usd_per_million_tokens=15)
    priced = apply_usage_price(
        UsageRecord(
            kind=UsageKind.ESTIMATED,
            input_tokens=1_000_000,
            output_tokens=1_000_000,
            provider="anthropic",
            model="x",
        ),
        policy,
    )
    assert priced.cost_usd == Decimal("18")


def test_preflight_starts_when_under_budget() -> None:
    policy = _compute_policy(max_budget_usd=1, input_usd_per_million_tokens=3)
    estimated = apply_input_price(
        UsageRecord(
            kind=UsageKind.ESTIMATED,
            input_tokens=100,
            provider="anthropic",
            model="x",
        ),
        policy,
    )
    assert preflight_budget(policy, estimated) is BudgetDecision.START


def test_preflight_refuses_uncertain_price_by_default() -> None:
    policy = _compute_policy()
    estimated = UsageRecord(
        kind=UsageKind.ESTIMATED,
        input_tokens=10,
        provider="anthropic",
        model="x",
    )
    assert estimated.cost_usd is None
    assert preflight_budget(policy, estimated) is BudgetDecision.REFUSE


def test_preflight_allows_uncertain_price_when_policy_says_so() -> None:
    policy = _compute_policy(allow_start_under_uncertain_price=True)
    estimated = UsageRecord(
        kind=UsageKind.ESTIMATED,
        input_tokens=10,
        provider="anthropic",
        model="x",
    )
    assert preflight_budget(policy, estimated) is BudgetDecision.START


@pytest.mark.asyncio
async def test_scripted_provider_returns_payload() -> None:
    provider = ScriptedProvider(payloads={"correctness": {"findings": []}})
    payload, usage = await provider.complete_structured(
        system="s",
        user="u",
        response_schema={},
        dimension_id="correctness",
    )
    assert payload == {"findings": []}
    assert usage.kind is UsageKind.MEASURED
    assert provider.dimension_ids_called == ["correctness"]
