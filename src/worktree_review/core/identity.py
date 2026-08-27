"""Merge-candidate and review identity (PRD §6.4, §8.2; TECH-DESIGN D2, D5)."""

from pydantic import BaseModel, ConfigDict, Field


class PolicyVersionIdentity(BaseModel):
    """Semver plus SHA-256 of the policy's canonical parsed bytes."""

    model_config = ConfigDict(frozen=True)

    semver: str
    sha256: str = Field(min_length=64, max_length=64)


class ReviewRequestKey(BaseModel):
    """Pre-construction key (PRD terminology). Exists even when merge construction fails."""

    model_config = ConfigDict(frozen=True)

    source_repository: str
    target_ref: str
    target_head_oid: str
    proposed_head_oid: str
    review_policy_version: PolicyVersionIdentity


class ResolvedCommitPair(BaseModel):
    """Target and proposed heads resolved to immutable commits, before merge."""

    model_config = ConfigDict(frozen=True)

    source_repository: str
    target_ref: str
    target_head_oid: str
    proposed_ref: str
    proposed_head_oid: str


class MergeCandidateIdentity(BaseModel):
    """Exact merge candidate: both parents and the resulting tree OID."""

    model_config = ConfigDict(frozen=True)

    source_repository: str
    target_ref: str
    target_head_oid: str
    proposed_head_oid: str
    merge_tree_oid: str


class ReviewIdentity(BaseModel):
    """What a completed review conclusion applies to: candidate plus Review Policy version.

    Platform change-request identifiers are provenance, not identity (PRD terminology).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    candidate: MergeCandidateIdentity
    review_policy_version: PolicyVersionIdentity
