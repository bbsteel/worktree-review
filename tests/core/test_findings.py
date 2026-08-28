from __future__ import annotations

from pathlib import Path

from worktree_review.core.context import ContextClass, ContextItem, GatheredContext
from worktree_review.core.findings import (
    ChangeKind,
    EvidenceBand,
    EvidenceSource,
    EvidenceSpan,
    Finding,
    Severity,
    fingerprint_finding,
    verify_and_deduplicate,
)
from worktree_review.core.report import CoverageRecord
from worktree_review.core.review_worktree import ReviewWorktree


def _review_worktree(tmp_path: Path, *, body: str = "first\nsecond\n") -> ReviewWorktree:
    tree_root = tmp_path / "tree"
    tree_root.mkdir()
    source_path = tree_root / "src" / "app.py"
    source_path.parent.mkdir()
    source_path.write_text(body, encoding="utf-8")
    return ReviewWorktree(
        root=tree_root,
        container_root=tmp_path,
        merge_tree_oid="a" * 40,
        owner_note="test",
    )


def _finding(
    *,
    path: str = "src/app.py",
    start_line: int = 1,
    end_line: int = 1,
    quoted_text: str = "first",
    problem_statement: str = "problem",
    evidence_band: EvidenceBand = EvidenceBand.SUPPORTED,
    evidence_spans: tuple[EvidenceSpan, ...] | None = None,
    dimension_id: str | None = "correctness",
    source: EvidenceSource = EvidenceSource.REVIEW_WORKTREE,
    snapshot_identity: str | None = None,
    change_kind: ChangeKind | None = None,
) -> Finding:
    spans = (
        evidence_spans
        if evidence_spans is not None
        else (
            EvidenceSpan(
                path=path,
                start_line=start_line,
                end_line=end_line,
                quoted_text=quoted_text,
                source=source,
                snapshot_identity=snapshot_identity,
                change_kind=change_kind,
            ),
        )
    )
    return Finding(
        fingerprint="provider-supplied-fingerprint",
        severity=Severity.MAJOR,
        evidence_band=evidence_band,
        problem_statement=problem_statement,
        expected_impact="impact",
        evidence_spans=spans,
        dimension_id=dimension_id,
    )


def test_grounded_worktree_evidence_keeps_band_and_recomputes_fingerprint(
    tmp_path: Path,
) -> None:
    finding = _finding(start_line=1, end_line=2, quoted_text="first\nsecond")

    [verified] = verify_and_deduplicate(
        (finding,),
        review_worktree=_review_worktree(tmp_path),
    )

    assert verified.evidence_band is EvidenceBand.SUPPORTED
    assert verified.fingerprint == fingerprint_finding(
        path="src/app.py",
        start_line=1,
        end_line=2,
        category="correctness",
        problem_statement="problem",
    )


def test_quote_may_be_a_fragment_within_the_declared_line_range(tmp_path: Path) -> None:
    finding = _finding(quoted_text="second")

    [verified] = verify_and_deduplicate(
        (finding,),
        review_worktree=_review_worktree(tmp_path, body="first second\n"),
    )

    assert verified.evidence_band is EvidenceBand.SUPPORTED


def test_grounded_quote_caps_provider_verified_band_at_supported(tmp_path: Path) -> None:
    finding = _finding(evidence_band=EvidenceBand.VERIFIED)

    [validated] = verify_and_deduplicate(
        (finding,),
        review_worktree=_review_worktree(tmp_path),
    )

    assert validated.evidence_band is EvidenceBand.SUPPORTED


def test_declared_review_worktree_source_cannot_use_target_context() -> None:
    gathered_context = GatheredContext(
        coverage=CoverageRecord(required_coverage_complete=True),
        items=(
            ContextItem(
                path="deleted.py",
                context_class=ContextClass.MANDATORY,
                source=EvidenceSource.TARGET_TREE,
                snapshot_identity="target-tree",
                change_kind=ChangeKind.DELETED,
                body="old implementation\n",
            ),
        ),
    )
    finding = _finding(path="deleted.py", quoted_text="old implementation")

    [validated] = verify_and_deduplicate((finding,), gathered_context=gathered_context)

    assert validated.evidence_band is EvidenceBand.INSUFFICIENT


def test_declared_target_source_can_ground_deleted_context() -> None:
    gathered_context = GatheredContext(
        coverage=CoverageRecord(required_coverage_complete=True),
        items=(
            ContextItem(
                path="deleted.py",
                context_class=ContextClass.MANDATORY,
                source=EvidenceSource.TARGET_TREE,
                snapshot_identity="target-tree",
                change_kind=ChangeKind.DELETED,
                body="old implementation\n",
            ),
        ),
    )
    finding = _finding(
        path="deleted.py",
        quoted_text="old implementation",
        source=EvidenceSource.TARGET_TREE,
        snapshot_identity="target-tree",
        change_kind=ChangeKind.DELETED,
    )

    [validated] = verify_and_deduplicate((finding,), gathered_context=gathered_context)

    assert validated.evidence_band is EvidenceBand.SUPPORTED
    assert validated.evidence_spans[0].source is EvidenceSource.TARGET_TREE
    assert validated.evidence_spans[0].snapshot_identity == "target-tree"


def test_mismatched_span_loses_enforcement_evidence() -> None:
    finding = _finding(quoted_text="not in the source")

    [verified] = verify_and_deduplicate(
        (finding,),
        review_worktree=ReviewWorktree(
            root=Path("/does/not/exist"),
            container_root=Path("/does/not"),
            merge_tree_oid="a" * 40,
            owner_note="test",
        ),
    )

    assert verified.evidence_band is EvidenceBand.INSUFFICIENT


def test_mismatched_verified_span_is_also_downgraded() -> None:
    finding = _finding(
        quoted_text="not in the source",
        evidence_band=EvidenceBand.VERIFIED,
    )

    [verified] = verify_and_deduplicate((finding,))

    assert verified.evidence_band is EvidenceBand.INSUFFICIENT


def test_an_unmatched_span_downgrades_the_whole_finding(tmp_path: Path) -> None:
    finding = _finding(
        evidence_spans=(
            EvidenceSpan(path="src/app.py", start_line=1, end_line=1, quoted_text="first"),
            EvidenceSpan(path="src/app.py", start_line=2, end_line=2, quoted_text="missing"),
        )
    )

    [verified] = verify_and_deduplicate(
        (finding,),
        review_worktree=_review_worktree(tmp_path),
    )

    assert verified.evidence_band is EvidenceBand.INSUFFICIENT


def test_normalized_path_and_span_fingerprint_deduplicate_findings(tmp_path: Path) -> None:
    first = _finding(path="./src/app.py")
    duplicate = _finding(path="src/app.py")

    verified = verify_and_deduplicate(
        (first, duplicate),
        review_worktree=_review_worktree(tmp_path),
    )

    assert len(verified) == 1
    assert verified[0].fingerprint == fingerprint_finding(
        path="src/app.py",
        start_line=1,
        end_line=1,
        category="correctness",
        problem_statement="problem",
    )


def test_deduplication_validates_all_findings_before_selecting_representative(
    tmp_path: Path,
) -> None:
    weak_finding = _finding(quoted_text="not present")
    grounded_finding = _finding(quoted_text="first")
    review_worktree = _review_worktree(tmp_path)

    weak_first = verify_and_deduplicate(
        (weak_finding, grounded_finding),
        review_worktree=review_worktree,
    )
    grounded_first = verify_and_deduplicate(
        (grounded_finding, weak_finding),
        review_worktree=review_worktree,
    )

    assert len(weak_first) == 1
    assert weak_first[0].evidence_band is EvidenceBand.SUPPORTED
    assert weak_first[0].evidence_spans[0].quoted_text == "first"
    assert weak_first == grounded_first


def test_provider_fingerprint_is_ignored_for_findings_without_evidence() -> None:
    first = _finding(evidence_spans=(), problem_statement="first problem")
    second = _finding(evidence_spans=(), problem_statement="second problem")

    validated = verify_and_deduplicate((first, second))

    assert len(validated) == 2
    assert {finding.fingerprint for finding in validated} == {
        fingerprint_finding(
            path="<worktree-review:no-evidence>",
            start_line=0,
            end_line=0,
            category="correctness",
            problem_statement="first problem",
        ),
        fingerprint_finding(
            path="<worktree-review:no-evidence>",
            start_line=0,
            end_line=0,
            category="correctness",
            problem_statement="second problem",
        ),
    }


def test_invalid_path_cannot_be_grounded_even_if_text_exists(tmp_path: Path) -> None:
    finding = _finding(path="../src/app.py")

    [verified] = verify_and_deduplicate(
        (finding,),
        review_worktree=_review_worktree(tmp_path),
    )

    assert verified.evidence_band is EvidenceBand.INSUFFICIENT


def test_missing_evidence_spans_cannot_retain_enforcement_band() -> None:
    finding = _finding(evidence_spans=())

    [verified] = verify_and_deduplicate((finding,))

    assert verified.evidence_band is EvidenceBand.INSUFFICIENT
