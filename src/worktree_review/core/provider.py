"""LLM provider abstraction and bounded compute enforcement (TECH-DESIGN D7)."""

from __future__ import annotations

import json
import os
from decimal import Decimal
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from worktree_review.core.config import ProviderConfiguration
from worktree_review.core.errors import BudgetExhaustedError, ProviderError
from worktree_review.core.policy import ComputePolicy, ProviderName

MILLION = Decimal("1000000")
DEFAULT_MAX_OUTPUT_TOKENS_PER_CALL = 8192


class UsageKind(StrEnum):
    """PRD §9.3 / §20: never present guesses as measured usage."""

    MEASURED = "measured"
    DECLARED = "declared"
    ESTIMATED = "estimated"


class UsageRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: UsageKind
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: Decimal | None = None
    provider: str
    model: str
    note: str | None = None


class ProviderClient(Protocol):
    """Provider-native structured output and usage metering. No multi-provider router."""

    provider_name: str
    model: str

    def estimate_input_tokens(self, text: str) -> UsageRecord:
        """Estimated input tokens for pre-flight. Kind is ESTIMATED, never MEASURED."""
        ...

    async def complete_structured(
        self,
        *,
        system: str,
        user: str,
        response_schema: dict[str, object],
        dimension_id: str,
        max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS_PER_CALL,
    ) -> tuple[dict[str, object], UsageRecord]:
        """Return the parsed structured payload and a measured usage record."""
        ...


class BudgetDecision(StrEnum):
    START = "start"
    REFUSE = "refuse"
    STOP_FURTHER_DIMENSIONS = "stop-further-dimensions"


def estimated_token_count_from_utf8_bytes(text: str) -> int:
    """Conservative heuristic when no provider tokenizer is available."""

    byte_length = len(text.encode("utf-8"))
    return max(1, (byte_length + 3) // 4)


def estimate_input_tokens_for_model(text: str, model: str) -> tuple[int, str]:
    """Return (token_count, note). Prefer tiktoken; fall back to the byte heuristic."""

    try:
        import tiktoken
    except ImportError:
        return estimated_token_count_from_utf8_bytes(text), "utf-8-bytes/4 heuristic"
    try:
        encoding = tiktoken.encoding_for_model(model)
        note = f"tiktoken encoding_for_model({model})"
    except KeyError:
        encoding = tiktoken.get_encoding("cl100k_base")
        note = f"tiktoken cl100k_base fallback (no encoding for {model})"
    return len(encoding.encode(text)), note


def apply_input_price(usage: UsageRecord, compute_policy: ComputePolicy) -> UsageRecord:
    """Backward-compatible alias for input-only pricing of older callers."""

    if usage.output_tokens:
        return apply_usage_price(usage, compute_policy)
    price = compute_policy.input_usd_per_million_tokens
    if price is None or usage.input_tokens is None:
        return usage
    cost = (Decimal(usage.input_tokens) / MILLION) * price
    return usage.model_copy(update={"cost_usd": cost})


def apply_usage_price(usage: UsageRecord, compute_policy: ComputePolicy) -> UsageRecord:
    """Price input and output tokens. Missing prices for present token counts → uncertain cost."""

    cost = Decimal("0")
    priced_any = False
    if usage.input_tokens is not None:
        input_price = compute_policy.input_usd_per_million_tokens
        if input_price is None:
            return usage.model_copy(update={"cost_usd": None})
        cost += (Decimal(usage.input_tokens) / MILLION) * input_price
        priced_any = True
    if usage.output_tokens is not None:
        output_price = compute_policy.output_usd_per_million_tokens
        if output_price is None:
            return usage.model_copy(update={"cost_usd": None})
        cost += (Decimal(usage.output_tokens) / MILLION) * output_price
        priced_any = True
    if not priced_any:
        return usage.model_copy(update={"cost_usd": None})
    return usage.model_copy(update={"cost_usd": cost})


def estimate_structured_call(
    *,
    system: str,
    user: str,
    response_schema: dict[str, object],
    provider_name: str,
    model: str,
    estimate_input_tokens: UsageRecord | None = None,
    max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS_PER_CALL,
) -> UsageRecord:
    """Pre-flight estimate for one dimension call, including schema and declared output."""

    schema_text = json.dumps(response_schema, sort_keys=True, separators=(",", ":"))
    assembled = f"{system}\n{user}\n{schema_text}"
    if estimate_input_tokens is not None:
        input_tokens = estimate_input_tokens.input_tokens
        note = estimate_input_tokens.note or "caller-supplied input estimate"
    else:
        input_tokens, note = estimate_input_tokens_for_model(assembled, model)
    return UsageRecord(
        kind=UsageKind.ESTIMATED,
        input_tokens=input_tokens,
        output_tokens=max_output_tokens,
        provider=provider_name,
        model=model,
        note=(f"{note}; includes system/user/schema and declared max output {max_output_tokens}"),
    )


def preflight_budget(compute_policy: ComputePolicy, estimated: UsageRecord) -> BudgetDecision:
    """Refuse to start when estimated cost exceeds max budget, unless policy allows uncertainty."""

    if compute_policy.max_budget_usd is None:
        return BudgetDecision.START
    if estimated.cost_usd is None:
        if compute_policy.allow_start_under_uncertain_price:
            return BudgetDecision.START
        return BudgetDecision.REFUSE
    if estimated.cost_usd > compute_policy.max_budget_usd:
        return BudgetDecision.REFUSE
    return BudgetDecision.START


def refuse_preflight(compute_policy: ComputePolicy, estimated: UsageRecord) -> BudgetExhaustedError:
    if estimated.cost_usd is None:
        return BudgetExhaustedError(
            "pre-flight price/usage is uncertain and Compute Policy "
            "allow_start_under_uncertain_price is false"
        )
    return BudgetExhaustedError(
        f"pre-flight estimated cost ${estimated.cost_usd} exceeds "
        f"max_budget_usd ${compute_policy.max_budget_usd}"
    )


class ScriptedProvider:
    """In-process provider for tests. Never calls a network API."""

    def __init__(
        self,
        *,
        payloads: dict[str, dict[str, object]],
        provider_name: str = "anthropic",
        model: str = "scripted",
        estimated_input_tokens: int | None = None,
        measured_input_tokens: int = 1,
        measured_output_tokens: int = 1,
    ) -> None:
        self.payloads = payloads
        self.provider_name = provider_name
        self.model = model
        self.estimated_input_tokens = estimated_input_tokens
        self.measured_input_tokens = measured_input_tokens
        self.measured_output_tokens = measured_output_tokens
        self.dimension_ids_called: list[str] = []

    def estimate_input_tokens(self, text: str) -> UsageRecord:
        if self.estimated_input_tokens is not None:
            tokens = self.estimated_input_tokens
            note = "scripted token estimate"
        else:
            tokens, note = estimate_input_tokens_for_model(text, self.model)
        return UsageRecord(
            kind=UsageKind.ESTIMATED,
            input_tokens=tokens,
            provider=self.provider_name,
            model=self.model,
            note=note,
        )

    async def complete_structured(
        self,
        *,
        system: str,
        user: str,
        response_schema: dict[str, object],
        dimension_id: str,
        max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS_PER_CALL,
    ) -> tuple[dict[str, object], UsageRecord]:
        del system, user, response_schema, max_output_tokens
        self.dimension_ids_called.append(dimension_id)
        payload = self.payloads.get(dimension_id)
        if payload is None:
            raise ProviderError(f"scripted provider has no payload for dimension {dimension_id}")
        return payload, UsageRecord(
            kind=UsageKind.MEASURED,
            input_tokens=self.measured_input_tokens,
            output_tokens=self.measured_output_tokens,
            provider=self.provider_name,
            model=self.model,
            note="scripted measured usage",
        )


def _require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ProviderError(f"{name} is not set; cannot call the configured provider")
    return value


def build_provider(
    compute_policy: ComputePolicy,
    provider_configuration: ProviderConfiguration | None = None,
) -> ProviderClient:
    """Construct the Compute-Policy-selected live provider. Tests should pass ScriptedProvider."""

    provider_name: ProviderName = compute_policy.provider
    if provider_configuration is not None:
        if provider_configuration.provider != provider_name:
            raise ProviderError(
                "provider configuration does not match the configured Compute Policy provider"
            )
        if provider_name == "local-cli":
            from worktree_review.core.providers.local_cli import LocalCliProvider

            return LocalCliProvider(
                command=provider_configuration.command,
                model=compute_policy.model,
            )
        if provider_configuration.api_key is None or provider_configuration.url is None:
            raise ProviderError("remote provider configuration requires url and key")
        api_key = provider_configuration.api_key.get_secret_value()
        if provider_name == "openai":
            from worktree_review.core.providers.openai import OpenAIProvider

            return OpenAIProvider(
                model=compute_policy.model,
                api_key=api_key,
                base_url=provider_configuration.url,
            )
        from worktree_review.core.providers.anthropic import AnthropicProvider

        return AnthropicProvider(
            model=compute_policy.model,
            api_key=api_key,
            base_url=provider_configuration.url,
        )
    if provider_name == "local-cli":
        raise ProviderError("local-cli provider requires a user configuration command")
    if provider_name == "openai":
        from worktree_review.core.providers.openai import OpenAIProvider

        return OpenAIProvider(model=compute_policy.model, api_key=_require_env("OPENAI_API_KEY"))
    from worktree_review.core.providers.anthropic import AnthropicProvider

    return AnthropicProvider(model=compute_policy.model, api_key=_require_env("ANTHROPIC_API_KEY"))
