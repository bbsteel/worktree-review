"""Mandatory / optional / excluded / unreviewable context gathering (PRD §10, §8.3)."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from mergegate.core.errors import UnimplementedStageError
from mergegate.core.policy import ReviewPolicy
from mergegate.core.report import CoverageRecord
from mergegate.core.workspace import ReviewWorkspace


class ContextClass(StrEnum):
    MANDATORY = "mandatory"
    OPTIONAL = "optional"
    EXCLUDED = "excluded"
    UNREVIEWABLE = "unreviewable"


class GatheredContext(BaseModel):
    model_config = ConfigDict(frozen=True)

    coverage: CoverageRecord
    items: tuple[str, ...] = ()


async def gather_context(
    workspace: ReviewWorkspace,
    review_policy: ReviewPolicy,
) -> GatheredContext:
    """Assemble context as quoted, delimited model input. Repository files are data."""

    raise UnimplementedStageError("context gathering is not implemented")
