"""Finding model, severity, evidence bands, and deterministic fingerprints."""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from worktree_review.core.context import GatheredContext
    from worktree_review.core.review_worktree import ReviewWorktree


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


class EvidenceSource(StrEnum):
    """Trusted origin of an evidence span; this is separate from context class."""

    REVIEW_WORKTREE = "review-worktree"
    TARGET_TREE = "target-tree"
    MERGE_DIFF = "merge-diff"
    METADATA = "metadata"


class ChangeKind(StrEnum):
    """How a repository path relates to the merge candidate."""

    ADDED = "added"
    MODIFIED = "modified"
    DELETED = "deleted"


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
    """A span tied to a declared source and immutable snapshot (D6)."""

    model_config = ConfigDict(frozen=True)

    path: str
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    quoted_text: str
    context_class: str = "workspace"
    source: EvidenceSource = EvidenceSource.REVIEW_WORKTREE
    snapshot_identity: str | None = None
    change_kind: ChangeKind | None = None


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


_NO_EVIDENCE_PATH = "<worktree-review:no-evidence>"
_SEVERITY_RANK: dict[Severity, int] = {
    Severity.SUGGESTION: 0,
    Severity.MINOR: 1,
    Severity.MAJOR: 2,
    Severity.CRITICAL: 3,
}


@dataclass(frozen=True)
class _EvidenceRecord:
    source: EvidenceSource
    snapshot_identity: str
    path: str
    change_kind: ChangeKind | None
    source_text: str


def _normalize_evidence_path(path: str) -> str | None:
    """Return a safe repository-relative path, or ``None`` for an invalid path."""

    normalized = path.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    if not normalized or normalized.startswith("/"):
        return None
    normalized_path_parts = tuple(normalized.split("/"))
    if any(part in ("", ".", "..") for part in normalized_path_parts):
        return None
    return normalized


def _read_review_worktree_text(
    review_worktree: ReviewWorktree | None,
    normalized_path: str,
) -> str | None:
    """Read one Review Worktree path without following repository symlinks."""

    if review_worktree is None:
        return None
    current_path = review_worktree.root
    try:
        root_status = current_path.lstat()
    except OSError:
        return None
    if not stat.S_ISDIR(root_status.st_mode):
        return None

    path_parts = tuple(normalized_path.split("/"))
    try:
        for part_index, part in enumerate(path_parts):
            current_path = current_path / part
            entry_status = current_path.lstat()
            is_final_part = part_index == len(path_parts) - 1
            if stat.S_ISLNK(entry_status.st_mode):
                if not is_final_part:
                    return None
                return os.readlink(current_path)
            if is_final_part:
                if not stat.S_ISREG(entry_status.st_mode):
                    return None
                return current_path.read_text(encoding="utf-8")
            if not stat.S_ISDIR(entry_status.st_mode):
                return None
    except (OSError, UnicodeDecodeError):
        return None
    return None


def _normalize_line_endings(source_text: str) -> str:
    return source_text.replace("\r\n", "\n").replace("\r", "\n")


def _line_range_text(source_text: str, *, start_line: int, end_line: int) -> str | None:
    if start_line < 1 or end_line < start_line:
        return None
    source_lines = _normalize_line_endings(source_text).splitlines()
    if end_line > len(source_lines):
        return None
    return "\n".join(source_lines[start_line - 1 : end_line])


def _quoted_text_matches(source_text: str, span: EvidenceSpan) -> bool:
    line_range_text = _line_range_text(
        source_text,
        start_line=span.start_line,
        end_line=span.end_line,
    )
    if line_range_text is None:
        return False
    quoted_text = _normalize_line_endings(span.quoted_text)
    if not quoted_text:
        return False
    if quoted_text in line_range_text:
        return True
    # A provider may include the line terminator in a quote. It is not part of
    # the source line selected by the inclusive line range, so accept exactly
    # one terminal newline while preserving all other whitespace.
    return quoted_text.endswith("\n") and quoted_text[:-1] in line_range_text


def _evidence_record_sort_key(
    evidence_record: _EvidenceRecord,
) -> tuple[str, str, str, str, str]:
    return (
        evidence_record.source.value,
        evidence_record.snapshot_identity,
        evidence_record.path,
        evidence_record.change_kind.value if evidence_record.change_kind else "",
        evidence_record.source_text,
    )


def _gathered_evidence_records(
    gathered_context: GatheredContext | None,
) -> tuple[_EvidenceRecord, ...]:
    if gathered_context is None:
        return ()
    records: list[_EvidenceRecord] = []
    for context_item in gathered_context.items:
        normalized_path = _normalize_evidence_path(context_item.path)
        snapshot_identity = context_item.snapshot_identity
        if normalized_path is None or context_item.body is None or not snapshot_identity:
            # A body without an immutable source snapshot is display context,
            # not trustworthy grounding material.
            continue
        records.append(
            _EvidenceRecord(
                source=context_item.source,
                snapshot_identity=snapshot_identity,
                path=normalized_path,
                change_kind=context_item.change_kind,
                source_text=context_item.body,
            )
        )
    return tuple(sorted(records, key=_evidence_record_sort_key))


def _records_for_span(
    span: EvidenceSpan,
    *,
    review_worktree: ReviewWorktree | None,
    gathered_records: tuple[_EvidenceRecord, ...],
    review_worktree_text_cache: dict[str, str | None],
) -> tuple[_EvidenceRecord, ...]:
    normalized_path = _normalize_evidence_path(span.path)
    if normalized_path is None:
        return ()

    requested_snapshot_identity = span.snapshot_identity or None
    if span.source == EvidenceSource.REVIEW_WORKTREE:
        current_snapshot_identity = (
            review_worktree.merge_tree_oid if review_worktree is not None else None
        )
        if requested_snapshot_identity is None:
            # A legacy provider payload may omit the local snapshot. Bind it to
            # the verifier's current merge tree; never infer a target/diff
            # snapshot from an untyped context item.
            requested_snapshot_identity = current_snapshot_identity
        if requested_snapshot_identity is None:
            return ()
    elif requested_snapshot_identity is None:
        return ()

    matching_context_records = tuple(
        record
        for record in gathered_records
        if record.source == span.source
        and record.snapshot_identity == requested_snapshot_identity
        and record.path == normalized_path
    )
    records = list(matching_context_records)
    if (
        span.source == EvidenceSource.REVIEW_WORKTREE
        and review_worktree is not None
        and requested_snapshot_identity == review_worktree.merge_tree_oid
    ):
        if normalized_path not in review_worktree_text_cache:
            review_worktree_text_cache[normalized_path] = _read_review_worktree_text(
                review_worktree,
                normalized_path,
            )
        review_worktree_text = review_worktree_text_cache[normalized_path]
        if review_worktree_text is not None:
            records.append(
                _EvidenceRecord(
                    source=EvidenceSource.REVIEW_WORKTREE,
                    snapshot_identity=review_worktree.merge_tree_oid,
                    path=normalized_path,
                    change_kind=None,
                    source_text=review_worktree_text,
                )
            )
    return tuple(sorted(records, key=_evidence_record_sort_key))


def _grounded_record_for_span(
    span: EvidenceSpan,
    *,
    review_worktree: ReviewWorktree | None,
    gathered_records: tuple[_EvidenceRecord, ...],
    review_worktree_text_cache: dict[str, str | None],
) -> _EvidenceRecord | None:
    for evidence_record in _records_for_span(
        span,
        review_worktree=review_worktree,
        gathered_records=gathered_records,
        review_worktree_text_cache=review_worktree_text_cache,
    ):
        if span.change_kind is not None and evidence_record.change_kind != span.change_kind:
            continue
        if _quoted_text_matches(evidence_record.source_text, span):
            return evidence_record
    return None


def _canonical_span(span: EvidenceSpan, evidence_record: _EvidenceRecord) -> EvidenceSpan:
    """Attach only verifier-observed provenance to a grounded span."""

    return span.model_copy(
        update={
            "path": evidence_record.path,
            "source": evidence_record.source,
            "snapshot_identity": evidence_record.snapshot_identity,
            "change_kind": evidence_record.change_kind,
        }
    )


def _fingerprint_span_key(span: EvidenceSpan) -> tuple[str, int, int] | None:
    normalized_path = _normalize_evidence_path(span.path)
    if normalized_path is None or span.end_line < span.start_line:
        return None
    return normalized_path, span.start_line, span.end_line


def _canonical_fingerprint(finding: Finding) -> str:
    """Recompute a deterministic D6 fingerprint without trusting provider input."""

    span_keys = tuple(
        span_key
        for span in finding.evidence_spans
        if (span_key := _fingerprint_span_key(span)) is not None
    )
    normalized_path, start_line, end_line = min(
        span_keys,
        default=(_NO_EVIDENCE_PATH, 0, 0),
    )
    return fingerprint_finding(
        path=normalized_path,
        start_line=start_line,
        end_line=end_line,
        category=finding.dimension_id or "",
        problem_statement=finding.problem_statement,
    )


def _verify_finding(
    finding: Finding,
    *,
    review_worktree: ReviewWorktree | None,
    gathered_records: tuple[_EvidenceRecord, ...],
    review_worktree_text_cache: dict[str, str | None],
) -> Finding:
    grounded_spans: list[EvidenceSpan] = []
    all_spans_grounded = bool(finding.evidence_spans)
    for span in finding.evidence_spans:
        evidence_record = _grounded_record_for_span(
            span,
            review_worktree=review_worktree,
            gathered_records=gathered_records,
            review_worktree_text_cache=review_worktree_text_cache,
        )
        if evidence_record is None:
            all_spans_grounded = False
            grounded_spans.append(span)
        else:
            grounded_spans.append(_canonical_span(span, evidence_record))

    # Grounding is a deterministic prerequisite for enforcement. It can derive
    # supported, but no provider-declared band can establish independent
    # verification, so the first-stage verifier intentionally caps at supported.
    derived_evidence_band = (
        EvidenceBand.SUPPORTED if all_spans_grounded else EvidenceBand.INSUFFICIENT
    )
    validated_finding = finding.model_copy(
        update={
            "fingerprint": _canonical_fingerprint(finding),
            "evidence_band": derived_evidence_band,
            "evidence_spans": tuple(grounded_spans),
        }
    )
    return validated_finding


def _merge_duplicate_findings(finding_group: tuple[Finding, ...]) -> Finding:
    """Merge duplicates conservatively after every member has been verified."""

    representative_finding = min(
        finding_group,
        key=lambda candidate: (
            -EVIDENCE_BAND_RANK[candidate.evidence_band],
            -_SEVERITY_RANK[candidate.severity],
            candidate.model_dump_json(),
        ),
    )
    strongest_evidence_band = max(
        (candidate.evidence_band for candidate in finding_group),
        key=EVIDENCE_BAND_RANK.__getitem__,
    )
    strongest_severity = max(
        (candidate.severity for candidate in finding_group),
        key=_SEVERITY_RANK.__getitem__,
    )
    return representative_finding.model_copy(
        update={
            "evidence_band": strongest_evidence_band,
            "severity": strongest_severity,
            # A duplicate may only keep a bypass if every representation agrees.
            "bypass_applied": all(candidate.bypass_applied for candidate in finding_group),
        }
    )


def verify_and_deduplicate(
    findings: tuple[Finding, ...],
    review_worktree: ReviewWorktree | None = None,
    gathered_context: GatheredContext | None = None,
) -> tuple[Finding, ...]:
    """Verify all findings, then deterministically and conservatively deduplicate.

    Each span must match its declared typed source and immutable snapshot. The
    ``context_class`` label is presentation context only and is not used as
    provenance. Provider evidence bands and fingerprints are never trusted.
    """

    gathered_records = _gathered_evidence_records(gathered_context)
    review_worktree_text_cache: dict[str, str | None] = {}

    findings_by_fingerprint: dict[str, list[Finding]] = {}
    for finding in findings:
        validated_finding = _verify_finding(
            finding,
            review_worktree=review_worktree,
            gathered_records=gathered_records,
            review_worktree_text_cache=review_worktree_text_cache,
        )
        findings_by_fingerprint.setdefault(validated_finding.fingerprint, []).append(
            validated_finding
        )

    return tuple(
        _merge_duplicate_findings(tuple(findings_by_fingerprint[fingerprint]))
        for fingerprint in sorted(findings_by_fingerprint)
    )
