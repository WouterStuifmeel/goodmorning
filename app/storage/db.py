from __future__ import annotations

import sqlite3
from pathlib import Path

from app.models.job import Job

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    episode_date TEXT NOT NULL,
    state TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    data TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_jobs_episode_date ON jobs (episode_date);
"""


class JobStore:
    """SQLite-backed job persistence.

    Synchronous by design - callers running inside an event loop should wrap
    calls in `asyncio.to_thread`. One connection per call keeps this safe to
    use from a thread pool without extra locking.
    """

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def save(self, job: Job) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO jobs (id, episode_date, state, created_at, updated_at, data)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    state = excluded.state,
                    updated_at = excluded.updated_at,
                    data = excluded.data
                """,
                (
                    job.id,
                    job.source_facts.episode_date.isoformat(),
                    job.state.value,
                    job.created_at.isoformat(),
                    job.updated_at.isoformat(),
                    job.model_dump_json(),
                ),
            )

    def get(self, job_id: str) -> Job | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT data FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
        return Job.model_validate_json(row[0]) if row else None

    def latest_for_date(self, episode_date: str) -> Job | None:
        """Most recently updated job for an episode date, for idempotent retries."""
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT data FROM jobs
                WHERE episode_date = ?
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (episode_date,),
            ).fetchone()
        return Job.model_validate_json(row[0]) if row else None

    def list_recent(self, limit: int = 50) -> list[Job]:
        """Most recently updated jobs, newest first."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT data FROM jobs ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [Job.model_validate_json(row[0]) for row in rows]
