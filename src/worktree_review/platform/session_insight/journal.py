"""Append-only Session Journal. Failures warn; they do not change Gate."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path

from worktree_review.application.review_events import ReviewEvent

logger = logging.getLogger(__name__)

METADATA_SCHEMA = "worktree-review.session-metadata/v1"


def default_journal_root() -> Path:
    override = os.environ.get("WORKTREE_REVIEW_JOURNAL_ROOT")
    if override:
        return Path(override)
    xdg = os.environ.get("XDG_STATE_HOME")
    if xdg:
        return Path(xdg) / "worktree-review" / "sessions"
    return Path.home() / ".local" / "state" / "worktree-review" / "sessions"


class SessionJournalWriter:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or default_journal_root()
        # Observation-only failure tracking: surfaced as a warning in the
        # integration status, never a Gate input.
        self.last_error: str | None = None
        self.last_error_at: str | None = None

    def _note_failure(self, exc: Exception) -> None:
        self.last_error = f"{exc.__class__.__name__}: {exc}"[:512]
        self.last_error_at = datetime.now(UTC).isoformat()

    def _attempt_dir(self, attempt_id: str) -> Path:
        return self.root / attempt_id

    def _write_metadata(self, attempt_id: str, last_sequence: int) -> None:
        directory = self._attempt_dir(attempt_id)
        directory.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema": METADATA_SCHEMA,
            "attempt_id": attempt_id,
            "heartbeat_at": datetime.now(UTC).isoformat(),
            "last_persisted_sequence": last_sequence,
        }
        tmp = directory / "metadata.json.tmp"
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(directory / "metadata.json")

    def _persisted_sequences(self, attempt_id: str) -> set[int]:
        path = self._attempt_dir(attempt_id) / "events.jsonl"
        if not path.is_file():
            return set()
        seen: set[int] = set()
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            loaded = json.loads(line)
            sequence = loaded.get("sequence")
            if isinstance(sequence, int):
                seen.add(sequence)
        return seen

    def last_sequence(self, attempt_id: str) -> int:
        metadata = self._attempt_dir(attempt_id) / "metadata.json"
        if metadata.is_file():
            loaded = json.loads(metadata.read_text(encoding="utf-8"))
            value = loaded.get("last_persisted_sequence")
            if isinstance(value, int):
                return value
        sequences = self._persisted_sequences(attempt_id)
        return max(sequences) if sequences else 0

    def touch_heartbeat(self, attempt_id: str) -> None:
        try:
            self._write_metadata(attempt_id, self.last_sequence(attempt_id))
        except Exception as exc:
            self._note_failure(exc)
            logger.warning("session journal heartbeat failed", exc_info=True)

    def append_event(self, event: ReviewEvent) -> None:
        directory = self._attempt_dir(event.attempt_id)
        directory.mkdir(parents=True, exist_ok=True)
        with (directory / "events.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(event.model_dump_json(by_alias=True) + "\n")
        self._write_metadata(event.attempt_id, event.sequence)

    async def publish(self, event: ReviewEvent) -> None:
        try:
            await asyncio.to_thread(self.append_event, event)
        except Exception as exc:
            self._note_failure(exc)
            logger.warning("session journal write failed", exc_info=True)

    def write_result(self, attempt_id: str, result_json: str) -> None:
        try:
            directory = self._attempt_dir(attempt_id)
            directory.mkdir(parents=True, exist_ok=True)
            target = directory / "result.json"
            if target.exists():
                return
            tmp = directory / "result.json.tmp"
            tmp.write_text(result_json, encoding="utf-8")
            tmp.replace(target)
        except Exception as exc:
            self._note_failure(exc)
            logger.warning("session journal result write failed", exc_info=True)

    def backfill(self, events: tuple[ReviewEvent, ...]) -> None:
        try:
            if not events:
                return
            attempt_id = events[0].attempt_id
            seen = self._persisted_sequences(attempt_id)
            for event in events:
                if event.sequence in seen:
                    continue
                self.append_event(event)
                seen.add(event.sequence)
        except Exception as exc:
            self._note_failure(exc)
            logger.warning("session journal backfill failed", exc_info=True)
