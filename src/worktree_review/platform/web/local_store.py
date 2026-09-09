"""SQLite ReviewRunStore for local Web."""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import UTC, datetime
from contextlib import closing
from pathlib import Path

from worktree_review.application.lifecycle import RunStatus
from worktree_review.application.review_events import ReviewEvent
from worktree_review.application.review_runs import OverviewAggregate, ReviewRunRecord
from worktree_review.core.errors import InvalidInvocationError
from worktree_review.core.report import ReviewReport


class IdempotencyConflictError(InvalidInvocationError):
    pass


class ResultImmutableError(InvalidInvocationError):
    pass


class SqliteReviewRunStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = asyncio.Lock()

    async def migrate(self) -> None:
        def _migrate() -> None:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            sql = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
            with closing(sqlite3.connect(self._path)) as connection:
                connection.executescript(sql)
                connection.execute(
                    "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (1, ?)",
                    (datetime.now(UTC).isoformat(),),
                )
                connection.commit()

        await asyncio.to_thread(_migrate)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    async def create_attempt_with_initial_event_and_idempotency(
        self,
        *,
        attempt_id: str,
        idempotency_key: str,
        request_digest: str,
        initial_event: ReviewEvent,
        run_status: RunStatus = RunStatus.QUEUED,
    ) -> str:
        def _create() -> str:
            now = datetime.now(UTC).isoformat()
            with closing(self._connect()) as connection:
                existing = connection.execute(
                    "SELECT attempt_id, request_digest FROM idempotency_records "
                    "WHERE idempotency_key = ?",
                    (idempotency_key,),
                ).fetchone()
                if existing is not None:
                    if existing["request_digest"] != request_digest:
                        raise IdempotencyConflictError(
                            "Idempotency-Key was reused with a different request"
                        )
                    return str(existing["attempt_id"])
                connection.execute(
                    "INSERT INTO review_runs("
                    "attempt_id, run_status, created_at, cost_unknown, interrupted) "
                    "VALUES (?, ?, ?, 0, 0)",
                    (attempt_id, run_status.value, now),
                )
                connection.execute(
                    "INSERT INTO review_events(attempt_id, sequence, event_json) VALUES (?, ?, ?)",
                    (
                        attempt_id,
                        initial_event.sequence,
                        initial_event.model_dump_json(by_alias=True),
                    ),
                )
                connection.execute(
                    "INSERT INTO idempotency_records("
                    "idempotency_key, request_digest, attempt_id, created_at) "
                    "VALUES (?, ?, ?, ?)",
                    (idempotency_key, request_digest, attempt_id, now),
                )
                connection.commit()
                return attempt_id

        async with self._lock:
            return await asyncio.to_thread(_create)

    async def append_event(self, event: ReviewEvent) -> None:
        def _append() -> None:
            with closing(self._connect()) as connection:
                connection.execute(
                    "INSERT INTO review_events(attempt_id, sequence, event_json) VALUES (?, ?, ?)",
                    (event.attempt_id, event.sequence, event.model_dump_json(by_alias=True)),
                )
                connection.commit()

        async with self._lock:
            await asyncio.to_thread(_append)

    async def update_run_status(self, attempt_id: str, run_status: RunStatus) -> None:
        def _update() -> None:
            with closing(self._connect()) as connection:
                connection.execute(
                    "UPDATE review_runs SET run_status = ? WHERE attempt_id = ?",
                    (run_status.value, attempt_id),
                )
                connection.commit()

        async with self._lock:
            await asyncio.to_thread(_update)

    async def save_result(
        self, report: ReviewReport, *, cost_usd: str | None, cost_unknown: bool
    ) -> None:
        if cost_unknown:
            cost_usd = None
        elif (
            cost_usd == "0"
            and report.usage
            and all(record.cost_usd is None for record in report.usage)
        ):
            raise InvalidInvocationError("unknown cost must not be stored as zero")

        def _save() -> None:
            now = datetime.now(UTC).isoformat()
            payload = report.model_dump_json()
            with closing(self._connect()) as connection:
                existing = connection.execute(
                    "SELECT attempt_id FROM review_results WHERE attempt_id = ?",
                    (report.attempt_id,),
                ).fetchone()
                if existing is not None:
                    raise ResultImmutableError("review result is immutable")
                connection.execute(
                    "INSERT INTO review_results(attempt_id, result_json, saved_at) "
                    "VALUES (?, ?, ?)",
                    (report.attempt_id, payload, now),
                )
                connection.execute(
                    "UPDATE review_runs SET gate_state = ?, cost_usd = ?, "
                    "cost_unknown = ?, run_status = ? "
                    "WHERE attempt_id = ?",
                    (
                        report.gate_state.value,
                        cost_usd,
                        1 if cost_unknown else 0,
                        RunStatus.COMPLETED.value,
                        report.attempt_id,
                    ),
                )
                connection.commit()

        async with self._lock:
            await asyncio.to_thread(_save)

    async def get_run(self, attempt_id: str) -> ReviewRunRecord | None:
        def _get() -> ReviewRunRecord | None:
            with closing(self._connect()) as connection:
                row = connection.execute(
                    "SELECT r.*, res.result_json FROM review_runs r "
                    "LEFT JOIN review_results res ON res.attempt_id = r.attempt_id "
                    "WHERE r.attempt_id = ?",
                    (attempt_id,),
                ).fetchone()
                if row is None:
                    return None
                return ReviewRunRecord(
                    attempt_id=row["attempt_id"],
                    run_status=RunStatus(row["run_status"]),
                    created_at=datetime.fromisoformat(row["created_at"]),
                    result_json=row["result_json"],
                    cost_usd=row["cost_usd"],
                    cost_unknown=bool(row["cost_unknown"]),
                    interrupted=bool(row["interrupted"]),
                )

        return await asyncio.to_thread(_get)

    async def list_events(self, attempt_id: str) -> tuple[ReviewEvent, ...]:
        def _list() -> tuple[ReviewEvent, ...]:
            with closing(self._connect()) as connection:
                rows = connection.execute(
                    "SELECT event_json FROM review_events WHERE attempt_id = ? ORDER BY sequence",
                    (attempt_id,),
                ).fetchall()
            return tuple(ReviewEvent.model_validate_json(row["event_json"]) for row in rows)

        return await asyncio.to_thread(_list)

    async def mark_interrupted(self, attempt_id: str) -> None:
        def _mark() -> None:
            with closing(self._connect()) as connection:
                connection.execute(
                    "UPDATE review_runs SET interrupted = 1, run_status = ? WHERE attempt_id = ?",
                    (RunStatus.INTERRUPTED.value, attempt_id),
                )
                connection.commit()

        async with self._lock:
            await asyncio.to_thread(_mark)

    async def overview_aggregate(self) -> OverviewAggregate:
        def _aggregate() -> OverviewAggregate:
            with closing(self._connect()) as connection:
                rows = connection.execute(
                    "SELECT gate_state, cost_usd, cost_unknown FROM review_runs"
                ).fetchall()
            attempt_count = len(rows)
            passed = sum(1 for row in rows if row["gate_state"] == "Passed")
            blocked = sum(1 for row in rows if row["gate_state"] == "Blocked")
            error = sum(1 for row in rows if row["gate_state"] == "Error")
            known_cost = 0.0
            unknown = 0
            for row in rows:
                if row["cost_unknown"]:
                    unknown += 1
                    continue
                if row["cost_usd"] is not None:
                    known_cost += float(row["cost_usd"])
            return OverviewAggregate(
                attempt_count=attempt_count,
                passed_count=passed,
                blocked_count=blocked,
                error_count=error,
                known_cost_usd=f"{known_cost:.2f}",
                unknown_cost_record_count=unknown,
            )

        return await asyncio.to_thread(_aggregate)

    async def insert_repository(
        self, *, repository_id: str, display_name: str, canonical_root: str
    ) -> None:
        def _insert() -> None:
            with closing(self._connect()) as connection:
                connection.execute(
                    "INSERT INTO repositories("
                    "id, display_name, canonical_root, created_at) VALUES (?, ?, ?, ?)",
                    (repository_id, display_name, canonical_root, datetime.now(UTC).isoformat()),
                )
                connection.commit()

        async with self._lock:
            await asyncio.to_thread(_insert)

    async def list_repositories(self) -> list[dict[str, str]]:
        def _list() -> list[dict[str, str]]:
            with closing(self._connect()) as connection:
                rows = connection.execute("SELECT * FROM repositories ORDER BY display_name")
                return [dict(row) for row in rows]

        return await asyncio.to_thread(_list)
