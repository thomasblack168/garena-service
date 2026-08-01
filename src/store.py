from __future__ import annotations

import sqlite3
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class JobRecord:
    ref: str
    partner_reference_id: str
    status: str
    completed_units: int
    total_units: int
    display_id: str | None
    failure_reason: str | None
    payload: dict[str, Any]


class JobStore:
    def __init__(self, db_path: Path) -> None:
        self._lock = threading.Lock()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
              ref TEXT PRIMARY KEY,
              partner_reference_id TEXT UNIQUE NOT NULL,
              status TEXT NOT NULL,
              completed_units INTEGER NOT NULL DEFAULT 0,
              total_units INTEGER NOT NULL DEFAULT 1,
              display_id TEXT,
              failure_reason TEXT,
              payload TEXT NOT NULL
            )
            """
        )
        self._conn.commit()

    def create_job(self, partner_reference_id: str, payload: dict[str, Any], quantity: int) -> JobRecord:
        with self._lock:
            existing = self._conn.execute(
                "SELECT ref FROM jobs WHERE partner_reference_id = ?",
                (partner_reference_id,),
            ).fetchone()
            if existing:
                raise DuplicateJobError(existing["ref"])

            ref = f"garena-{uuid.uuid4().hex[:12]}"
            import json

            self._conn.execute(
                """
                INSERT INTO jobs (ref, partner_reference_id, status, total_units, payload)
                VALUES (?, ?, 'accepted', ?, ?)
                """,
                (ref, partner_reference_id, quantity, json.dumps(payload)),
            )
            self._conn.commit()
            row = self._conn.execute("SELECT * FROM jobs WHERE ref = ?", (ref,)).fetchone()
            return self._row_to_job(row)

    def get_by_ref(self, ref: str) -> JobRecord | None:
        row = self._conn.execute("SELECT * FROM jobs WHERE ref = ?", (ref,)).fetchone()
        return self._row_to_job(row) if row else None

    def get_by_partner_ref(self, partner_reference_id: str) -> JobRecord | None:
        row = self._conn.execute(
            "SELECT * FROM jobs WHERE partner_reference_id = ?",
            (partner_reference_id,),
        ).fetchone()
        return self._row_to_job(row) if row else None

    def update_job(
        self,
        ref: str,
        *,
        status: str,
        completed_units: int,
        display_id: str | None = None,
        failure_reason: str | None = None,
    ) -> None:
        with self._lock:
            self._conn.execute(
                """
                UPDATE jobs
                SET status = ?, completed_units = ?, display_id = ?, failure_reason = ?
                WHERE ref = ?
                """,
                (status, completed_units, display_id, failure_reason, ref),
            )
            self._conn.commit()

    def list_accepted(self, limit: int = 20) -> list[JobRecord]:
        rows = self._conn.execute(
            "SELECT * FROM jobs WHERE status IN ('accepted', 'processing') ORDER BY ref LIMIT ?",
            (limit,),
        ).fetchall()
        return [self._row_to_job(row) for row in rows]

    def _row_to_job(self, row: sqlite3.Row) -> JobRecord:
        import json

        return JobRecord(
            ref=row["ref"],
            partner_reference_id=row["partner_reference_id"],
            status=row["status"],
            completed_units=row["completed_units"],
            total_units=row["total_units"],
            display_id=row["display_id"],
            failure_reason=row["failure_reason"],
            payload=json.loads(row["payload"]),
        )


class DuplicateJobError(Exception):
    def __init__(self, ref: str) -> None:
        super().__init__(f"duplicate partner reference: {ref}")
        self.ref = ref
