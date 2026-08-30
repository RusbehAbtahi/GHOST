"""Persist CLI confirmations and asynchronous jobs for GHOST.

SQLite keeps command state owner-scoped and available across MCP process
restarts. Confirmation tokens are stored only as SHA-256 digests and bind one
owner, one server-side pending command, and one execution mode.

Main classes:
    StoredCommandJob:
        Immutable representation of one persisted command job.
    CommandStore:
        Owns the CLI SQLite schema and state transitions.

Main methods:
    issue_confirmation(), consume_confirmation():
        Create and consume short-lived, exact-command confirmation tokens.
    create_job(), get_job():
        Persist and retrieve owner-scoped command jobs.
    update_backend_job(), complete_job():
        Record backend identity and terminal command results.
"""

from __future__ import annotations

import hashlib
import secrets
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path

DEFAULT_CLI_STATE_PATH = Path("data/mcp/cli/command_state.sqlite3")
TERMINAL_JOB_STATUSES = frozenset({"succeeded", "failed", "cancelled", "timed_out"})


@dataclass(frozen=True)
class StoredCommandJob:
    """Represent one durable command job without exposing another owner."""

    job_id: str
    owner_sub: str
    command: str
    execution_mode: str
    backend: str
    backend_job_id: str | None
    status: str
    exit_code: int | None
    stdout: str
    stderr: str
    truncated: bool
    working_directory: str
    shell_executable: str
    command_timeout_seconds: int
    max_output_bytes: int


@dataclass(frozen=True)
class PendingConfirmation:
    """Return the public identifier and secret for one pending command."""

    confirmation_id: str
    confirmation_token: str


class CommandStore:
    """Own durable, owner-scoped CLI state in one SQLite database."""

    def __init__(
        self,
        sqlite_path: str | Path = DEFAULT_CLI_STATE_PATH,
        confirmation_ttl_seconds: int = 1_200,
    ) -> None:
        if confirmation_ttl_seconds < 1:
            raise ValueError("confirmation_ttl_seconds must be positive")

        self.sqlite_path = Path(sqlite_path)
        self.confirmation_ttl_seconds = confirmation_ttl_seconds
        self._lock = threading.Lock()
        self.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize_schema()

    def issue_confirmation(
        self,
        owner_sub: str,
        command: str,
        execution_mode: str,
        reason: str,
    ) -> PendingConfirmation:
        """Persist one exact command and return its public ID and secret."""
        self._require_owner(owner_sub)
        confirmation_id = secrets.token_urlsafe(24)
        token = secrets.token_urlsafe(32)
        token_digest = self._token_digest(token)
        now = time.time()

        with self._lock, self._connect() as connection:
            connection.execute(
                "DELETE FROM cli_confirmations WHERE expires_at_epoch <= ?",
                (now,),
            )
            connection.execute(
                """
                INSERT INTO cli_confirmations (
                    confirmation_id,
                    token_digest,
                    owner_sub,
                    command,
                    execution_mode,
                    reason,
                    expires_at_epoch
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    confirmation_id,
                    token_digest,
                    owner_sub,
                    command,
                    execution_mode,
                    reason,
                    now + self.confirmation_ttl_seconds,
                ),
            )
            connection.commit()

        return PendingConfirmation(
            confirmation_id=confirmation_id,
            confirmation_token=token,
        )

    def consume_confirmation(
        self,
        owner_sub: str,
        confirmation_id: str,
        token: str,
        execution_mode: str,
    ) -> str | None:
        """Consume a valid pending request and return its exact command."""
        self._require_owner(owner_sub)
        if not isinstance(confirmation_id, str) or not confirmation_id:
            return None
        if not isinstance(token, str) or not token:
            return None

        token_digest = self._token_digest(token)
        now = time.time()
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT command, execution_mode, expires_at_epoch
                FROM cli_confirmations
                WHERE confirmation_id = ?
                  AND token_digest = ?
                  AND owner_sub = ?
                """,
                (confirmation_id, token_digest, owner_sub),
            ).fetchone()

            if row is None:
                return None
            if float(row["expires_at_epoch"]) <= now:
                connection.execute(
                    "DELETE FROM cli_confirmations WHERE token_digest = ?",
                    (token_digest,),
                )
                connection.commit()
                return None
            if row["execution_mode"] != execution_mode:
                return None

            connection.execute(
                "DELETE FROM cli_confirmations WHERE token_digest = ?",
                (token_digest,),
            )
            connection.commit()
            return str(row["command"])

    def create_job(
        self,
        owner_sub: str,
        command: str,
        execution_mode: str,
        backend: str,
        working_directory: str,
        shell_executable: str,
        command_timeout_seconds: int,
        max_output_bytes: int,
        backend_job_id: str | None = None,
    ) -> StoredCommandJob:
        """Create one in-progress job and return its public identifier."""
        self._require_owner(owner_sub)
        job_id = secrets.token_urlsafe(24)
        now = time.time()

        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO cli_jobs (
                    job_id,
                    owner_sub,
                    command,
                    execution_mode,
                    backend,
                    backend_job_id,
                    status,
                    working_directory,
                    shell_executable,
                    command_timeout_seconds,
                    max_output_bytes,
                    created_at_epoch,
                    updated_at_epoch
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    owner_sub,
                    command,
                    execution_mode,
                    backend,
                    backend_job_id,
                    "in_progress",
                    working_directory,
                    shell_executable,
                    command_timeout_seconds,
                    max_output_bytes,
                    now,
                    now,
                ),
            )
            connection.commit()

        job = self.get_job(owner_sub, job_id)
        assert job is not None
        return job

    def get_job(self, owner_sub: str, job_id: str) -> StoredCommandJob | None:
        """Return a job only when it belongs to the authenticated owner."""
        self._require_owner(owner_sub)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM cli_jobs WHERE job_id = ? AND owner_sub = ?",
                (job_id, owner_sub),
            ).fetchone()
        return self._job_from_row(row)

    def get_job_for_worker(self, job_id: str) -> StoredCommandJob | None:
        """Return a local job to the detached worker that owns its random ID."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM cli_jobs WHERE job_id = ?",
                (job_id,),
            ).fetchone()
        return self._job_from_row(row)

    def update_backend_job(self, job_id: str, backend_job_id: str) -> None:
        """Attach the backend process or SSM command identifier to a job."""
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE cli_jobs
                SET backend_job_id = ?, updated_at_epoch = ?
                WHERE job_id = ?
                """,
                (backend_job_id, time.time(), job_id),
            )
            connection.commit()

    def complete_job(
        self,
        job_id: str,
        status: str,
        exit_code: int | None,
        stdout: str,
        stderr: str,
        truncated: bool,
    ) -> None:
        """Store one terminal result produced by a command backend."""
        if status not in TERMINAL_JOB_STATUSES:
            raise ValueError("status must be terminal")

        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE cli_jobs
                SET status = ?,
                    exit_code = ?,
                    stdout = ?,
                    stderr = ?,
                    truncated = ?,
                    updated_at_epoch = ?
                WHERE job_id = ?
                """,
                (
                    status,
                    exit_code,
                    stdout,
                    stderr,
                    int(truncated),
                    time.time(),
                    job_id,
                ),
            )
            connection.commit()

    def _initialize_schema(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS cli_confirmations (
                    confirmation_id TEXT,
                    token_digest TEXT PRIMARY KEY,
                    owner_sub TEXT NOT NULL,
                    command TEXT NOT NULL,
                    execution_mode TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    expires_at_epoch REAL NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_cli_confirmations_owner
                    ON cli_confirmations(owner_sub, expires_at_epoch);

                CREATE TABLE IF NOT EXISTS cli_jobs (
                    job_id TEXT PRIMARY KEY,
                    owner_sub TEXT NOT NULL,
                    command TEXT NOT NULL,
                    execution_mode TEXT NOT NULL,
                    backend TEXT NOT NULL,
                    backend_job_id TEXT,
                    status TEXT NOT NULL,
                    exit_code INTEGER,
                    stdout TEXT NOT NULL DEFAULT '',
                    stderr TEXT NOT NULL DEFAULT '',
                    truncated INTEGER NOT NULL DEFAULT 0,
                    working_directory TEXT NOT NULL,
                    shell_executable TEXT NOT NULL,
                    command_timeout_seconds INTEGER NOT NULL,
                    max_output_bytes INTEGER NOT NULL,
                    created_at_epoch REAL NOT NULL,
                    updated_at_epoch REAL NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_cli_jobs_owner
                    ON cli_jobs(owner_sub, created_at_epoch);
                """
            )
            columns = {
                str(row["name"])
                for row in connection.execute(
                    "PRAGMA table_info(cli_confirmations)"
                ).fetchall()
            }
            if "confirmation_id" not in columns:
                connection.execute(
                    "ALTER TABLE cli_confirmations "
                    "ADD COLUMN confirmation_id TEXT"
                )
                connection.execute(
                    "UPDATE cli_confirmations "
                    "SET confirmation_id = token_digest "
                    "WHERE confirmation_id IS NULL"
                )
            connection.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS "
                "idx_cli_confirmations_public_id "
                "ON cli_confirmations(confirmation_id)"
            )
            connection.commit()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.sqlite_path, timeout=30.0)
        connection.row_factory = sqlite3.Row
        return connection

    @staticmethod
    def _job_from_row(row: sqlite3.Row | None) -> StoredCommandJob | None:
        if row is None:
            return None
        return StoredCommandJob(
            job_id=str(row["job_id"]),
            owner_sub=str(row["owner_sub"]),
            command=str(row["command"]),
            execution_mode=str(row["execution_mode"]),
            backend=str(row["backend"]),
            backend_job_id=(
                str(row["backend_job_id"])
                if row["backend_job_id"] is not None
                else None
            ),
            status=str(row["status"]),
            exit_code=(int(row["exit_code"]) if row["exit_code"] is not None else None),
            stdout=str(row["stdout"]),
            stderr=str(row["stderr"]),
            truncated=bool(row["truncated"]),
            working_directory=str(row["working_directory"]),
            shell_executable=str(row["shell_executable"]),
            command_timeout_seconds=int(row["command_timeout_seconds"]),
            max_output_bytes=int(row["max_output_bytes"]),
        )

    @staticmethod
    def _token_digest(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    @staticmethod
    def _require_owner(owner_sub: str) -> None:
        if not isinstance(owner_sub, str) or not owner_sub.strip():
            raise ValueError("owner_sub must be a non-empty string")
