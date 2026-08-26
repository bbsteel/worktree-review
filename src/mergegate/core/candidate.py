"""Merge-candidate construction via ``git merge-tree --write-tree`` (TECH-DESIGN D2)."""

from mergegate.core.errors import UnimplementedStageError
from mergegate.core.identity import MergeCandidateIdentity, ResolvedCommitPair


async def construct_merge_candidate(
    resolved: ResolvedCommitPair,
) -> MergeCandidateIdentity:
    """Compute the merge tree in a bare object store. Fail closed on conflict.

    Must not check out or execute proposed-change code. Not implemented in the
    skeleton; the pipeline records this stage as failed.
    """

    raise UnimplementedStageError("git merge-tree --write-tree construction is not implemented")
