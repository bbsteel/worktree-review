"""Map merge-candidate absolute lines to GitHub-commentable positions (D13).

Findings live on the merge-candidate diff (resolved target head … merge tree).
GitHub only accepts comments on its three-dot PR diff. Unmappable findings
degrade to file-level comments or the check summary, with the reason disclosed.
"""

from pydantic import BaseModel, ConfigDict


class InlinePlacement(BaseModel):
    model_config = ConfigDict(frozen=True)

    path: str
    position: int


class Placement(BaseModel):
    model_config = ConfigDict(frozen=True)

    inline: InlinePlacement | None = None
    file_level: bool = False
    summary_only: bool = False
    reason: str | None = None


def commentable_new_side_lines(unified_diff: str) -> frozenset[tuple[str, int]]:
    """Parse hunk headers of a controlled ``git diff`` into (path, new-side line) pairs."""

    raise NotImplementedError("inline diff mapping is not implemented")
