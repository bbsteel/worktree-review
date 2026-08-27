"""Mandatory / optional / excluded / unreviewable context gathering (PRD §10, §8.3).

Gathering is deterministic and closed before any model call. Repository files
are untrusted data. Coverage is always disclosed; missing mandatory context or
in-scope unreviewable changed content makes required coverage incomplete.
"""

from __future__ import annotations

import fnmatch
import os
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from mergegate.core.errors import ContextGatherError
from mergegate.core.git import (
    GitCliError,
    commit_tree_oid,
    diff_name_status,
    git_blob_bytes,
    run_git,
)
from mergegate.core.identity import MergeCandidateIdentity
from mergegate.core.policy import ReviewPolicy
from mergegate.core.report import CoverageRecord
from mergegate.core.workspace import ReviewWorkspace

MERGE_CANDIDATE_DIFF_PATH = "merge-candidate.diff"
_NUL_SCAN_BYTES = 8192


class ContextClass(StrEnum):
    MANDATORY = "mandatory"
    OPTIONAL = "optional"
    EXCLUDED = "excluded"
    UNREVIEWABLE = "unreviewable"


class ChangeKind(StrEnum):
    ADDED = "added"
    MODIFIED = "modified"
    DELETED = "deleted"


class ContextItem(BaseModel):
    """One gathered unit. Body is omitted for excluded, unreviewable, and missing paths."""

    model_config = ConfigDict(frozen=True)

    path: str
    context_class: ContextClass
    change_kind: ChangeKind | None = None
    body: str | None = None
    untrusted: bool = True
    omission_reason: str | None = None

    def as_delimited(self) -> str:
        header = f"----- BEGIN CONTEXT path={self.path} class={self.context_class.value} -----"
        if self.body is None:
            reason = self.omission_reason or "omitted"
            inner = f"(omitted: {reason})"
        else:
            inner = self.body
        footer = f"----- END CONTEXT path={self.path} -----"
        return f"{header}\n{inner}\n{footer}\n"


class GatheredContext(BaseModel):
    model_config = ConfigDict(frozen=True)

    coverage: CoverageRecord
    items: tuple[ContextItem, ...] = ()


def _normalize_relative_path(relative_path: str) -> str:
    """Strip only ``./`` prefixes. ``str.lstrip('./')`` would also strip ``.env``."""

    normalized = relative_path.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    if normalized.startswith("/"):
        normalized = normalized.lstrip("/")
    return normalized


def path_matches_glob(relative_path: str, pattern: str) -> bool:
    normalized = _normalize_relative_path(relative_path)
    basename = normalized.rsplit("/", 1)[-1]
    if fnmatch.fnmatch(normalized, pattern) or fnmatch.fnmatch(basename, pattern):
        return True
    if pattern.startswith("**/") and fnmatch.fnmatch(normalized, pattern[3:]):
        return True
    if "/" not in pattern.rstrip("/") and fnmatch.fnmatch(normalized, f"**/{pattern}"):
        return True
    return False


def path_matches_any_glob(relative_path: str, patterns: tuple[str, ...]) -> bool:
    return any(path_matches_glob(relative_path, pattern) for pattern in patterns)


def unreviewable_reason(data: bytes, *, max_file_bytes: int) -> str | None:
    if len(data) > max_file_bytes:
        return f"exceeds max_file_bytes ({len(data)} > {max_file_bytes})"
    if b"\x00" in data[:_NUL_SCAN_BYTES]:
        return "binary (NUL byte)"
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return "not valid UTF-8"
    if text.startswith("version https://git-lfs.github.com/spec/v1"):
        return "git-lfs pointer"
    return None


def _change_kind(status: str) -> ChangeKind:
    if status == "A":
        return ChangeKind.ADDED
    if status == "D":
        return ChangeKind.DELETED
    return ChangeKind.MODIFIED


def _list_workspace_relative_paths(root: Path) -> tuple[str, ...]:
    relative_paths: list[str] = []
    for dirpath, _dirnames, filenames in os.walk(root, followlinks=False):
        for name in filenames:
            full = Path(dirpath) / name
            relative = full.relative_to(root).as_posix()
            relative_paths.append(relative)
    return tuple(sorted(relative_paths))


def _read_workspace_bytes(root: Path, relative_path: str) -> bytes | None:
    path = root.joinpath(*relative_path.split("/"))
    try:
        resolved_root = root.resolve()
        resolved_path = path.resolve()
        resolved_path.relative_to(resolved_root)
    except (OSError, ValueError):
        return None
    if not path.exists() or path.is_symlink() or not path.is_file():
        if path.is_symlink():
            try:
                return os.readlink(path).encode("utf-8")
            except OSError:
                return None
        return None
    try:
        return path.read_bytes()
    except OSError:
        return None


def _item_from_bytes(
    *,
    path: str,
    data: bytes | None,
    context_class: ContextClass,
    change_kind: ChangeKind | None,
    max_file_bytes: int,
    missing_reason: str,
) -> ContextItem:
    if data is None:
        return ContextItem(
            path=path,
            context_class=ContextClass.UNREVIEWABLE
            if context_class is ContextClass.MANDATORY
            else context_class,
            change_kind=change_kind,
            omission_reason=missing_reason,
        )
    reason = unreviewable_reason(data, max_file_bytes=max_file_bytes)
    if reason is not None:
        return ContextItem(
            path=path,
            context_class=ContextClass.UNREVIEWABLE,
            change_kind=change_kind,
            omission_reason=reason,
        )
    return ContextItem(
        path=path,
        context_class=context_class,
        change_kind=change_kind,
        body=data.decode("utf-8"),
        untrusted=True,
    )


async def _unified_diff(
    *,
    repository: Path,
    from_tree: str,
    to_tree: str,
    paths: tuple[str, ...],
    max_file_bytes: int,
) -> ContextItem:
    if not paths:
        return ContextItem(
            path=MERGE_CANDIDATE_DIFF_PATH,
            context_class=ContextClass.MANDATORY,
            body="",
            untrusted=True,
        )
    try:
        stdout = await run_git(
            "diff",
            "--no-renames",
            "--no-color",
            "--no-ext-diff",
            from_tree,
            to_tree,
            "--",
            *paths,
            cwd=repository,
        )
    except GitCliError as exc:
        raise ContextGatherError(f"git diff for merge-candidate context failed: {exc}") from exc
    data = stdout.encode("utf-8")
    reason = unreviewable_reason(data, max_file_bytes=max_file_bytes)
    if reason is not None:
        return ContextItem(
            path=MERGE_CANDIDATE_DIFF_PATH,
            context_class=ContextClass.UNREVIEWABLE,
            omission_reason=reason,
        )
    return ContextItem(
        path=MERGE_CANDIDATE_DIFF_PATH,
        context_class=ContextClass.MANDATORY,
        body=stdout,
        untrusted=True,
    )


def _coverage_from_items(
    items: tuple[ContextItem, ...],
    *,
    mandatory_missing: tuple[str, ...],
    optional_missing: tuple[str, ...],
) -> CoverageRecord:
    excluded = tuple(item.path for item in items if item.context_class is ContextClass.EXCLUDED)
    unreviewable = tuple(
        f"{item.path} ({item.omission_reason})" if item.omission_reason else item.path
        for item in items
        if item.context_class is ContextClass.UNREVIEWABLE
    )
    reviewed = tuple(
        item.path
        for item in items
        if item.context_class in (ContextClass.MANDATORY, ContextClass.OPTIONAL)
        and item.body is not None
    )
    required_coverage_complete = not mandatory_missing and not unreviewable
    return CoverageRecord(
        required_coverage_complete=required_coverage_complete,
        mandatory_missing=mandatory_missing,
        optional_missing=optional_missing,
        excluded=excluded,
        unreviewable=unreviewable,
        reviewed=reviewed,
    )


async def gather_context(
    workspace: ReviewWorkspace,
    candidate: MergeCandidateIdentity,
    review_policy: ReviewPolicy,
) -> GatheredContext:
    """Assemble quoted, delimited context from the merge tree and object store."""

    repository = Path(candidate.source_repository)
    context_policy = review_policy.context
    if not workspace.root.is_dir():
        raise ContextGatherError(f"workspace does not exist: {workspace.root}")

    try:
        target_tree = await commit_tree_oid(candidate.target_head_oid, repository)
        changes = await diff_name_status(
            from_tree=target_tree,
            to_tree=candidate.merge_tree_oid,
            repository=repository,
        )
    except GitCliError as exc:
        raise ContextGatherError(f"cannot list merge-candidate changes: {exc}") from exc

    items: list[ContextItem] = []
    classified_paths: set[str] = set()

    in_scope_diff_paths: list[str] = []
    for status, path in changes:
        classified_paths.add(path)
        kind = _change_kind(status)
        if path_matches_any_glob(path, context_policy.excluded_globs):
            items.append(
                ContextItem(
                    path=path,
                    context_class=ContextClass.EXCLUDED,
                    change_kind=kind,
                    omission_reason="excluded by Review Policy",
                )
            )
            continue
        in_scope_diff_paths.append(path)
        data: bytes | None
        if kind is ChangeKind.DELETED:
            try:
                data = await git_blob_bytes(f"{candidate.target_head_oid}:{path}", repository)
            except GitCliError:
                data = None
            item = _item_from_bytes(
                path=path,
                data=data,
                context_class=ContextClass.MANDATORY,
                change_kind=kind,
                max_file_bytes=context_policy.max_file_bytes,
                missing_reason="deleted path could not be read from the target head",
            )
        else:
            data = _read_workspace_bytes(workspace.root, path)
            item = _item_from_bytes(
                path=path,
                data=data,
                context_class=ContextClass.MANDATORY,
                change_kind=kind,
                max_file_bytes=context_policy.max_file_bytes,
                missing_reason="changed path is missing from the merge-candidate workspace",
            )
        items.append(item)

    diff_item = await _unified_diff(
        repository=repository,
        from_tree=target_tree,
        to_tree=candidate.merge_tree_oid,
        paths=tuple(in_scope_diff_paths),
        max_file_bytes=context_policy.max_file_bytes,
    )
    items.insert(0, diff_item)

    workspace_paths = _list_workspace_relative_paths(workspace.root)

    mandatory_missing: list[str] = []
    for pattern in context_policy.mandatory_globs:
        matches = [path for path in workspace_paths if path_matches_glob(path, pattern)]
        if not matches:
            mandatory_missing.append(pattern)
            continue
        for path in matches:
            if path in classified_paths:
                continue
            if path_matches_any_glob(path, context_policy.excluded_globs):
                continue
            classified_paths.add(path)
            data = _read_workspace_bytes(workspace.root, path)
            items.append(
                _item_from_bytes(
                    path=path,
                    data=data,
                    context_class=ContextClass.MANDATORY,
                    change_kind=None,
                    max_file_bytes=context_policy.max_file_bytes,
                    missing_reason="mandatory path could not be read",
                )
            )

    optional_missing: list[str] = []
    for pattern in context_policy.optional_globs:
        matches = [path for path in workspace_paths if path_matches_glob(path, pattern)]
        if not matches:
            optional_missing.append(pattern)
            continue
        for path in matches:
            if path in classified_paths:
                continue
            if path_matches_any_glob(path, context_policy.excluded_globs):
                continue
            classified_paths.add(path)
            data = _read_workspace_bytes(workspace.root, path)
            item = _item_from_bytes(
                path=path,
                data=data,
                context_class=ContextClass.OPTIONAL,
                change_kind=None,
                max_file_bytes=context_policy.max_file_bytes,
                missing_reason="optional path could not be read",
            )
            if item.context_class is ContextClass.UNREVIEWABLE:
                items.append(
                    ContextItem(
                        path=path,
                        context_class=ContextClass.OPTIONAL,
                        omission_reason=item.omission_reason,
                    )
                )
                optional_missing.append(path)
                continue
            items.append(item)

    coverage = _coverage_from_items(
        tuple(items),
        mandatory_missing=tuple(mandatory_missing),
        optional_missing=tuple(optional_missing),
    )
    return GatheredContext(coverage=coverage, items=tuple(items))
