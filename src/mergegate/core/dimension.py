"""Required review dimensions (PRD §11.1). Concurrent, I/O-bound, fail-closed."""

from pydantic import BaseModel, ConfigDict

from mergegate.core.context import GatheredContext
from mergegate.core.errors import UnimplementedStageError
from mergegate.core.findings import Finding
from mergegate.core.policy import ReviewPolicy
from mergegate.core.provider import ProviderClient
from mergegate.core.report import DimensionOutcome
from mergegate.core.workspace import ReviewWorkspace


class DimensionRunResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    outcome: DimensionOutcome
    findings: tuple[Finding, ...] = ()


async def run_required_dimensions(
    workspace: ReviewWorkspace,
    context: GatheredContext,
    review_policy: ReviewPolicy,
    provider: ProviderClient,
) -> tuple[DimensionRunResult, ...]:
    """Run every required dimension against the same workspace and context."""

    raise UnimplementedStageError("required review dimensions are not implemented")
