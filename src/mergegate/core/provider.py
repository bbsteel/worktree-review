"""LLM provider abstraction and three-point budget enforcement (TECH-DESIGN D7)."""

from decimal import Decimal
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from mergegate.core.errors import UnimplementedStageError
from mergegate.core.policy import ComputePolicy


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

    async def complete_structured(
        self,
        *,
        system: str,
        user: str,
        response_schema: dict[str, object],
    ) -> tuple[dict[str, object], UsageRecord]:
        """Return the parsed structured payload and a measured usage record."""
        ...


class BudgetDecision(StrEnum):
    START = "start"
    REFUSE = "refuse"
    STOP_FURTHER_DIMENSIONS = "stop-further-dimensions"


def preflight_budget(
    compute_policy: ComputePolicy,
    estimated: UsageRecord,
) -> BudgetDecision:
    """Refuse to start when estimated cost exceeds max budget, unless policy allows it."""

    raise UnimplementedStageError("pre-flight budget enforcement is not implemented")
