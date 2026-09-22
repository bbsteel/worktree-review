"""SQLite ReviewRunStore for local Web."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from worktree_review.application.lifecycle import RunStatus
from worktree_review.application.review_events import ReviewEvent
from worktree_review.application.review_runs import OverviewAggregate, ReviewRunRecord
from worktree_review.core.errors import InvalidInvocationError
from worktree_review.core.report import ReviewReport
from worktree_review.platform.cli.result import cli_result_document


class IdempotencyConflictError(InvalidInvocationError):
    pass


class ResultImmutableError(InvalidInvocationError):
    pass


def _table_columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in connection.execute(f"PRAGMA table_info({table})").fetchall()}


def _migrate_v3(connection: sqlite3.Connection) -> None:
    """v3: full Provider Profile fields, Compute Policy profile binding, frozen Attempt provider."""

    profile_columns = _table_columns(connection, "provider_profiles")
    if "local_cli_adapter" not in profile_columns:
        connection.execute("ALTER TABLE provider_profiles ADD COLUMN local_cli_adapter TEXT")
    if "local_cli_command" not in profile_columns:
        connection.execute("ALTER TABLE provider_profiles ADD COLUMN local_cli_command TEXT")
    if "adapter_label" not in profile_columns:
        connection.execute("ALTER TABLE provider_profiles ADD COLUMN adapter_label TEXT")
    compute_columns = _table_columns(connection, "trusted_compute_policies")
    if "provider_profile_id" not in compute_columns:
        connection.execute(
            "ALTER TABLE trusted_compute_policies ADD COLUMN provider_profile_id TEXT"
        )
    if "source_format" not in compute_columns:
        connection.execute("ALTER TABLE trusted_compute_policies ADD COLUMN source_format TEXT")
    run_columns = _table_columns(connection, "review_runs")
    if "frozen_provider_json" not in run_columns:
        connection.execute("ALTER TABLE review_runs ADD COLUMN frozen_provider_json TEXT")


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
                columns = {
                    row[1]
                    for row in connection.execute("PRAGMA table_info(review_runs)").fetchall()
                }
                if "request_json" not in columns:
                    connection.execute("ALTER TABLE review_runs ADD COLUMN request_json TEXT")
                connection.execute(
                    "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (2, ?)",
                    (datetime.now(UTC).isoformat(),),
                )
                _migrate_v3(connection)
                connection.execute(
                    "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (3, ?)",
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
        request_json: str | None = None,
        frozen_provider_json: str | None = None,
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
                    "attempt_id, run_status, created_at, cost_unknown, interrupted, "
                    "request_json, frozen_provider_json) VALUES (?, ?, ?, 0, 0, ?, ?)",
                    (attempt_id, run_status.value, now, request_json, frozen_provider_json),
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

    async def append(self, event: ReviewEvent) -> None:
        await self.append_event(event)

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
            # Persist the canonical versioned result document — the same shape
            # the CLI emits and GET /result serves — never the internal report.
            payload = cli_result_document(report).model_dump_json(by_alias=True)
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
                return self._record_from_row(row)

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

    async def insert_trusted_policy(
        self,
        *,
        table: str,
        policy_id: str,
        path: str,
        version_semver: str,
        version_sha256: str,
        provider_profile_id: str | None = None,
        source_format: str | None = None,
    ) -> None:
        if table not in {"trusted_review_policies", "trusted_compute_policies"}:
            raise InvalidInvocationError("unknown policy table")

        def _insert() -> None:
            with closing(self._connect()) as connection:
                if table == "trusted_compute_policies":
                    connection.execute(
                        "INSERT INTO trusted_compute_policies("
                        "id, path, version_semver, version_sha256, provider_profile_id, "
                        "source_format, registered_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (
                            policy_id,
                            path,
                            version_semver,
                            version_sha256,
                            provider_profile_id,
                            source_format,
                            datetime.now(UTC).isoformat(),
                        ),
                    )
                else:
                    connection.execute(
                        "INSERT INTO trusted_review_policies("
                        "id, path, version_semver, version_sha256, registered_at) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (
                            policy_id,
                            path,
                            version_semver,
                            version_sha256,
                            datetime.now(UTC).isoformat(),
                        ),
                    )
                connection.commit()

        async with self._lock:
            await asyncio.to_thread(_insert)

    async def insert_provider_profile(
        self,
        *,
        profile_id: str,
        name: str,
        provider: str,
        credential_reference: str | None,
        endpoint: str | None = None,
        local_cli_adapter: str | None = None,
        local_cli_command: list[str] | None = None,
        adapter_label: str | None = None,
    ) -> None:
        def _insert() -> None:
            with closing(self._connect()) as connection:
                connection.execute(
                    "INSERT INTO provider_profiles("
                    "id, name, provider, endpoint, credential_reference, "
                    "local_cli_adapter, local_cli_command, adapter_label, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        profile_id,
                        name,
                        provider,
                        endpoint,
                        credential_reference,
                        local_cli_adapter,
                        (None if local_cli_command is None else json.dumps(local_cli_command)),
                        adapter_label,
                        datetime.now(UTC).isoformat(),
                    ),
                )
                connection.commit()

        async with self._lock:
            await asyncio.to_thread(_insert)

    async def list_provider_profiles(self) -> list[dict[str, str | None]]:
        def _list() -> list[dict[str, str | None]]:
            with closing(self._connect()) as connection:
                rows = connection.execute("SELECT * FROM provider_profiles ORDER BY name")
                return [dict(row) for row in rows]

        return await asyncio.to_thread(_list)

    async def list_repositories(self) -> list[dict[str, str]]:
        def _list() -> list[dict[str, str]]:
            with closing(self._connect()) as connection:
                rows = connection.execute("SELECT * FROM repositories ORDER BY display_name")
                return [dict(row) for row in rows]

        return await asyncio.to_thread(_list)

    async def get_repository(self, repository_id: str) -> dict[str, str] | None:
        def _get() -> dict[str, str] | None:
            with closing(self._connect()) as connection:
                row = connection.execute(
                    "SELECT * FROM repositories WHERE id = ?", (repository_id,)
                ).fetchone()
                return None if row is None else dict(row)

        return await asyncio.to_thread(_get)

    async def delete_repository(self, repository_id: str) -> bool:
        def _delete() -> bool:
            with closing(self._connect()) as connection:
                cursor = connection.execute(
                    "DELETE FROM repositories WHERE id = ?", (repository_id,)
                )
                connection.commit()
                return cursor.rowcount > 0

        async with self._lock:
            return await asyncio.to_thread(_delete)

    async def list_runs(self, *, limit: int = 50) -> tuple[ReviewRunRecord, ...]:
        def _list() -> tuple[ReviewRunRecord, ...]:
            with closing(self._connect()) as connection:
                rows = connection.execute(
                    "SELECT r.*, res.result_json FROM review_runs r "
                    "LEFT JOIN review_results res ON res.attempt_id = r.attempt_id "
                    "ORDER BY r.created_at DESC, r.attempt_id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return tuple(self._record_from_row(row) for row in rows)

        return await asyncio.to_thread(_list)

    async def list_incomplete_attempt_ids(self) -> tuple[str, ...]:
        def _list() -> tuple[str, ...]:
            with closing(self._connect()) as connection:
                rows = connection.execute(
                    "SELECT attempt_id FROM review_runs "
                    "WHERE run_status IN ('queued', 'preparing', 'running', 'interrupted') "
                    "AND attempt_id NOT IN (SELECT attempt_id FROM review_results) "
                    "ORDER BY created_at"
                ).fetchall()
            return tuple(str(row["attempt_id"]) for row in rows)

        return await asyncio.to_thread(_list)

    async def list_trusted_policies(self, table: str) -> list[dict[str, str]]:
        if table not in {"trusted_review_policies", "trusted_compute_policies"}:
            raise InvalidInvocationError("unknown policy table")

        def _list() -> list[dict[str, str]]:
            with closing(self._connect()) as connection:
                rows = connection.execute(f"SELECT * FROM {table} ORDER BY registered_at")
                return [dict(row) for row in rows]

        return await asyncio.to_thread(_list)

    async def get_trusted_policy(self, table: str, policy_id: str) -> dict[str, str] | None:
        if table not in {"trusted_review_policies", "trusted_compute_policies"}:
            raise InvalidInvocationError("unknown policy table")

        def _get() -> dict[str, str] | None:
            with closing(self._connect()) as connection:
                row = connection.execute(
                    f"SELECT * FROM {table} WHERE id = ?", (policy_id,)
                ).fetchone()
                return None if row is None else dict(row)

        return await asyncio.to_thread(_get)

    def update_trusted_policy_identity_sync(
        self,
        *,
        table: str,
        policy_id: str,
        version_semver: str,
        version_sha256: str,
        source_format: str | None = None,
    ) -> bool:
        """Update registered Policy identity from a worker already holding a file lock."""

        if table not in {"trusted_review_policies", "trusted_compute_policies"}:
            raise InvalidInvocationError("unknown policy table")
        with closing(self._connect()) as connection:
            if table == "trusted_compute_policies":
                cursor = connection.execute(
                    "UPDATE trusted_compute_policies SET version_semver = ?, "
                    "version_sha256 = ?, source_format = ? WHERE id = ?",
                    (version_semver, version_sha256, source_format, policy_id),
                )
            else:
                cursor = connection.execute(
                    "UPDATE trusted_review_policies SET version_semver = ?, "
                    "version_sha256 = ? WHERE id = ?",
                    (version_semver, version_sha256, policy_id),
                )
            connection.commit()
            return cursor.rowcount > 0

    async def update_trusted_policy_identity(
        self,
        *,
        table: str,
        policy_id: str,
        version_semver: str,
        version_sha256: str,
        source_format: str | None = None,
    ) -> bool:
        async with self._lock:
            return await asyncio.to_thread(
                self.update_trusted_policy_identity_sync,
                table=table,
                policy_id=policy_id,
                version_semver=version_semver,
                version_sha256=version_sha256,
                source_format=source_format,
            )

    async def delete_trusted_policy(self, table: str, policy_id: str) -> bool:
        if table not in {"trusted_review_policies", "trusted_compute_policies"}:
            raise InvalidInvocationError("unknown policy table")

        def _delete() -> bool:
            with closing(self._connect()) as connection:
                cursor = connection.execute(f"DELETE FROM {table} WHERE id = ?", (policy_id,))
                connection.commit()
                return cursor.rowcount > 0

        async with self._lock:
            return await asyncio.to_thread(_delete)

    async def get_provider_profile(self, profile_id: str) -> dict[str, str | None] | None:
        def _get() -> dict[str, str | None] | None:
            with closing(self._connect()) as connection:
                row = connection.execute(
                    "SELECT * FROM provider_profiles WHERE id = ?", (profile_id,)
                ).fetchone()
                return None if row is None else dict(row)

        return await asyncio.to_thread(_get)

    async def update_provider_profile(
        self,
        *,
        profile_id: str,
        name: str,
        provider: str,
        credential_reference: str | None,
        endpoint: str | None = None,
        local_cli_adapter: str | None = None,
        local_cli_command: list[str] | None = None,
        adapter_label: str | None = None,
    ) -> None:
        def _update() -> None:
            with closing(self._connect()) as connection:
                connection.execute(
                    "UPDATE provider_profiles SET name = ?, provider = ?, endpoint = ?, "
                    "credential_reference = ?, local_cli_adapter = ?, "
                    "local_cli_command = ?, adapter_label = ? WHERE id = ?",
                    (
                        name,
                        provider,
                        endpoint,
                        credential_reference,
                        local_cli_adapter,
                        (None if local_cli_command is None else json.dumps(local_cli_command)),
                        adapter_label,
                        profile_id,
                    ),
                )
                connection.commit()

        async with self._lock:
            await asyncio.to_thread(_update)

    async def provider_profile_in_use(self, profile_id: str) -> bool:
        """True when any Attempt froze a reference to this profile."""

        def _check() -> bool:
            with closing(self._connect()) as connection:
                row = connection.execute(
                    "SELECT 1 FROM review_runs WHERE frozen_provider_json LIKE ? LIMIT 1",
                    (f'%"profile_id":"{profile_id}"%',),
                ).fetchone()
                return row is not None

        return await asyncio.to_thread(_check)

    async def delete_provider_profile(self, profile_id: str) -> bool:
        def _delete() -> bool:
            with closing(self._connect()) as connection:
                cursor = connection.execute(
                    "DELETE FROM provider_profiles WHERE id = ?", (profile_id,)
                )
                connection.commit()
                return cursor.rowcount > 0

        async with self._lock:
            return await asyncio.to_thread(_delete)

    def _record_from_row(self, row: sqlite3.Row) -> ReviewRunRecord:
        keys = set(row.keys())
        return ReviewRunRecord(
            attempt_id=row["attempt_id"],
            run_status=RunStatus(row["run_status"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            result_json=row["result_json"] if "result_json" in keys else None,
            cost_usd=row["cost_usd"],
            cost_unknown=bool(row["cost_unknown"]),
            interrupted=bool(row["interrupted"]),
            request_json=row["request_json"] if "request_json" in keys else None,
            gate_state=row["gate_state"],
            frozen_provider_json=(
                row["frozen_provider_json"] if "frozen_provider_json" in keys else None
            ),
        )
