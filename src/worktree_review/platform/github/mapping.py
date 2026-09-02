"""Map merge-candidate absolute lines to GitHub-commentable positions (D13).

Findings live on the merge-candidate diff (resolved target head … merge tree).
GitHub only accepts comments on its three-dot PR diff. Unmappable findings
degrade to file-level comments or the check summary, with the reason disclosed.
"""

from __future__ import annotations

import re

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

    commentable_lines: set[tuple[str, int]] = set()
    current_path: str | None = None
    for diff_line in unified_diff.splitlines():
        if diff_line.startswith("+++ "):
            current_path = _decode_diff_path(diff_line[4:])
            continue
        if not diff_line.startswith("@@"):
            continue
        hunk_match = _HUNK_HEADER.fullmatch(diff_line)
        if hunk_match is None:
            raise ValueError(f"invalid unified-diff hunk header: {diff_line!r}")
        new_start = int(hunk_match.group("new_start"))
        new_count = int(hunk_match.group("new_count") or "1")
        if new_count == 0:
            continue
        if current_path is None:
            raise ValueError("unified-diff hunk has no destination path")
        commentable_lines.update(
            (current_path, new_line) for new_line in range(new_start, new_start + new_count)
        )
    return frozenset(commentable_lines)


_HUNK_HEADER = re.compile(r"@@ -\d+(?:,\d+)? \+(?P<new_start>\d+)(?:,(?P<new_count>\d+))? @@.*")


def _decode_diff_path(raw_path: str) -> str | None:
    """Decode one Git ``+++`` path, including Git's quoted path form."""

    path = _decode_git_quoted_path(raw_path) if raw_path.startswith('"') else raw_path
    if path == "/dev/null":
        return None
    if path.startswith("a/") or path.startswith("b/"):
        path = path[2:]
    if not path or path.startswith("/") or "\x00" in path:
        raise ValueError(f"invalid unified-diff destination path: {raw_path!r}")
    path_parts = tuple(path.split("/"))
    if any(part in ("", ".", "..") for part in path_parts):
        raise ValueError(f"invalid unified-diff destination path: {raw_path!r}")
    return path


def _decode_git_quoted_path(raw_path: str) -> str:
    if len(raw_path) < 2 or not raw_path.endswith('"'):
        raise ValueError(f"unterminated quoted unified-diff path: {raw_path!r}")
    decoded_bytes = bytearray()
    path_index = 1
    while path_index < len(raw_path) - 1:
        path_character = raw_path[path_index]
        if path_character != "\\":
            decoded_bytes.extend(path_character.encode("utf-8"))
            path_index += 1
            continue
        path_index += 1
        if path_index >= len(raw_path) - 1:
            raise ValueError(f"invalid quoted unified-diff path: {raw_path!r}")
        escaped_character = raw_path[path_index]
        if escaped_character in "01234567":
            octal_start = path_index
            path_index += 1
            while (
                path_index < len(raw_path) - 1
                and path_index < octal_start + 3
                and raw_path[path_index] in "01234567"
            ):
                path_index += 1
            decoded_bytes.append(int(raw_path[octal_start:path_index], 8))
            continue
        escaped_bytes = {
            "a": b"\a",
            "b": b"\b",
            "t": b"\t",
            "n": b"\n",
            "v": b"\v",
            "f": b"\f",
            "r": b"\r",
            "\\": b"\\",
            '"': b'"',
        }.get(escaped_character)
        if escaped_bytes is None:
            raise ValueError(f"invalid escape in unified-diff path: {raw_path!r}")
        decoded_bytes.extend(escaped_bytes)
        path_index += 1
    try:
        return decoded_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"quoted unified-diff path is not UTF-8: {raw_path!r}") from exc
