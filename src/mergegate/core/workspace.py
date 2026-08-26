"""Isolated read-only materialization of a merge-candidate tree (TECH-DESIGN D2)."""

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from mergegate.core.errors import UnimplementedStageError
from mergegate.core.identity import MergeCandidateIdentity


class ReviewWorkspace(BaseModel):
    """A disposable directory containing the merge tree, chmod'd read-only."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    root: Path
    merge_tree_oid: str
    owner_note: str = Field(
        description="Dedicated unprivileged runtime user (server) or invoking user (CLI)."
    )


async def materialize_read_only_workspace(
    candidate: MergeCandidateIdentity,
    destination: Path,
) -> ReviewWorkspace:
    """``git archive <tree> | tar -x`` into a fresh directory, then chmod read-only."""

    raise UnimplementedStageError("read-only workspace materialization is not implemented")
