"""Finding model, severity, evidence bands, and deterministic fingerprints."""

from enum import StrEnum
from hashlib import sha256

from pydantic import BaseModel, ConfigDict, Field

from worktree_review.core.errors import UnimplementedStageError


class Severity(StrEnum):
    """PRD §12."""

    CRITICAL = "critical"
    MAJOR = "major"
    MINOR = "minor"
    SUGGESTION = "suggestion"


class EvidenceBand(StrEnum):
    """PRD §13. Self-reported model certainty is not an evidence band."""

    INSUFFICIENT = "insufficient"
    SUPPORTED = "supported"
    VERIFIED = "verified"


EVIDENCE_BAND_RANK: dict[EvidenceBand, int] = {
    EvidenceBand.INSUFFICIENT: 0,
    EvidenceBand.SUPPORTED: 1,
    EvidenceBand.VERIFIED: 2,
}

DEFAULT_BLOCKING_SEVERITIES: tuple[Severity, ...] = (
    Severity.CRITICAL,
    Severity.MAJOR,
)
DEFAULT_MINIMUM_BLOCKING_EVIDENCE_BAND = EvidenceBand.SUPPORTED


class EvidenceSpan(BaseModel):
    """A grounded span that must exist in the Review Worktree or gathered context (D6)."""

    model_config = ConfigDict(frozen=True)

    path: str
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    quoted_text: str
    context_class: str = "workspace"


class Finding(BaseModel):
    """Surface-neutral finding. Bypass flags are resolved before gate evaluation."""

    model_config = ConfigDict(frozen=True)

    fingerprint: str
    severity: Severity
    evidence_band: EvidenceBand
    problem_statement: str
    expected_impact: str
    evidence_spans: tuple[EvidenceSpan, ...] = ()
    repair_guidance: str | None = None
    bypass_applied: bool = False
    dimension_id: str | None = None


def fingerprint_finding(
    *,
    path: str,
    start_line: int,
    end_line: int,
    category: str,
    problem_statement: str,
) -> str:
    """Deterministic fingerprint over path, normalized span, category, and problem hash (D6)."""

    payload = f"{path}\0{start_line}\0{end_line}\0{category}\0{problem_statement}"
    return sha256(payload.encode("utf-8")).hexdigest()


def verify_and_deduplicate(findings: tuple[Finding, ...]) -> tuple[Finding, ...]:
    """Drop ungrounded claims from supported/verified bands; fingerprint-dedup the rest."""

    raise UnimplementedStageError("finding verification and deduplication is not implemented")
