"""Trusted execution context. Distinct from canonical repository identity."""

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class ReviewExecutionContext(BaseModel):
    """How and where this Attempt is executed.

    ``repository_path`` is a server-authorized local Git directory. Canonical
    repository identity stays on ReviewRequestKey / ResolvedCommitPair / Identity.
    """

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    repository_path: Path
    attempt_id: str = Field(min_length=1)
    surface: str
