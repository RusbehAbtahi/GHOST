"""Coordinate synchronous and asynchronous CLI execution for GHOST.

The service exposes one backend API to the future MCP adapter. Local
development uses a detached subprocess worker; the AWS deployment uses SSM Run
Command against the configured fixed EC2 instance. The backend choice comes
from configuration, so the committed Python code remains identical in both
environments.

Main classes:
    CommandConfig:
        Validated execution and persistence settings loaded from environment.
    CommandOutcome:
        Stable backend result returned to the MCP adapter.
    CommandService:
        Applies policy, starts commands, and retrieves owner-scoped results.

Main methods:
    run_sync():
        Starts one command and waits briefly for its result.
    start_async():
        Starts one command and immediately returns its durable job ID.
    get_async_result():
        Retrieves the latest state of one owner-scoped job.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ragstream.cli.command_policy import CommandPolicy
from ragstream.cli.command_store import (
    DEFAULT_CLI_STATE_PATH,
    TERMINAL_JOB_STATUSES,
    CommandStore,
    StoredCommandJob,
)

DEFAULT_AWS_REGION = "eu-central-1"
DEFAULT_SYNC_WAIT_SECONDS = 20.0
DEFAULT_POLL_INTERVAL_SECONDS = 0.25
DEFAULT_MAX_OUTPUT_BYTES = 65_536
DEFAULT_COMMAND_TIMEOUT_SECONDS = 3_600
DEFAULT_CONFIRMATION_TTL_SECONDS = 1_200
MAX_COMMAND_CHARACTERS = 32_768
VALID_CONFIRMATION_PROFILES = frozenset({"auto", "strict", "trusted_local"})

_SYNC_MODE = "synchronous"
_ASYNC_MODE = "asynchronous"
_SSM_IN_PROGRESS_STATUSES = frozenset({"Pending", "InProgress", "Delayed"})
_SSM_TIMED_OUT_STATUSES = frozenset(
    {"TimedOut", "Delivery Timed Out", "Execution Timed Out"}
)


class CommandServiceError(RuntimeError):
    """Report a sanitized command-backend failure to the MCP boundary."""


@dataclass(frozen=True)
class CommandConfig:
    """Hold validated CLI backend settings shared by service and workers."""

    backend: str = "local"
    state_path: Path = DEFAULT_CLI_STATE_PATH
    target_instance_id: str | None = None
    aws_region: str = DEFAULT_AWS_REGION
    working_directory: Path = field(default_factory=Path.cwd)
    shell_executable: str = "/bin/bash"
    sync_wait_seconds: float = DEFAULT_SYNC_WAIT_SECONDS
    poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS
    max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES
    command_timeout_seconds: int = DEFAULT_COMMAND_TIMEOUT_SECONDS
    confirmation_ttl_seconds: int = DEFAULT_CONFIRMATION_TTL_SECONDS
    confirmation_profile: str = "auto"

    def __post_init__(self) -> None:
        if self.backend not in {"local", "ssm"}:
            raise ValueError("GHOST_CLI_BACKEND must be 'local' or 'ssm'")
        if self.backend == "ssm" and not self.target_instance_id:
            raise ValueError(
                "GHOST_CLI_TARGET_INSTANCE_ID is required for the SSM backend"
            )
        if self.confirmation_profile not in VALID_CONFIRMATION_PROFILES:
            raise ValueError(
                "GHOST_CLI_CONFIRMATION_PROFILE must be 'auto', "
                "'strict', or 'trusted_local'"
            )
        if self.confirmation_profile == "auto":
            resolved_profile = (
                "trusted_local" if self.backend == "local" else "strict"
            )
            object.__setattr__(self, "confirmation_profile", resolved_profile)
        if self.sync_wait_seconds <= 0:
            raise ValueError("sync_wait_seconds must be positive")
        if self.poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds must be positive")
        if self.max_output_bytes < 1:
            raise ValueError("max_output_bytes must be positive")
        if self.command_timeout_seconds < 1:
            raise ValueError("command_timeout_seconds must be positive")
        if self.confirmation_ttl_seconds < 1:
            raise ValueError("confirmation_ttl_seconds must be positive")
        if not self.working_directory.is_dir():
            raise ValueError("GHOST_CLI_WORKING_DIRECTORY must exist")
        if not self.shell_executable:
            raise ValueError("shell_executable must be configured")

    @classmethod
    def from_environment(cls) -> CommandConfig:
        """Build configuration without changing the committed codebase."""
        return cls(
            backend=os.getenv("GHOST_CLI_BACKEND", "local").strip().lower(),
            state_path=Path(
                os.getenv("GHOST_CLI_STATE_PATH", str(DEFAULT_CLI_STATE_PATH))
            ),
            target_instance_id=(os.getenv("GHOST_CLI_TARGET_INSTANCE_ID") or None),
            aws_region=os.getenv("AWS_REGION", DEFAULT_AWS_REGION),
            working_directory=Path(
                os.getenv("GHOST_CLI_WORKING_DIRECTORY", str(Path.cwd()))
            ),
            shell_executable=os.getenv("GHOST_CLI_SHELL", "/bin/bash"),
            sync_wait_seconds=_environment_float(
                "GHOST_CLI_SYNC_WAIT_SECONDS",
                DEFAULT_SYNC_WAIT_SECONDS,
            ),
            poll_interval_seconds=_environment_float(
                "GHOST_CLI_POLL_INTERVAL_SECONDS",
                DEFAULT_POLL_INTERVAL_SECONDS,
            ),
            max_output_bytes=_environment_int(
                "GHOST_CLI_MAX_OUTPUT_BYTES",
                DEFAULT_MAX_OUTPUT_BYTES,
            ),
            command_timeout_seconds=_environment_int(
                "GHOST_CLI_COMMAND_TIMEOUT_SECONDS",
                DEFAULT_COMMAND_TIMEOUT_SECONDS,
            ),
            confirmation_ttl_seconds=_environment_int(
                "GHOST_CLI_CONFIRM_TTL_SECONDS",
                DEFAULT_CONFIRMATION_TTL_SECONDS,
            ),
            confirmation_profile=os.getenv(
                "GHOST_CLI_CONFIRMATION_PROFILE",
                "auto",
            ).strip().lower(),
        )


@dataclass(frozen=True)
class CommandOutcome:
    """Return stable command state without exposing backend exceptions."""

    status: str
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    truncated: bool = False
    job_id: str | None = None
    confirmation_required: bool = False
    confirmation_id: str | None = None
    confirmation_token: str | None = None
    message: str = ""


class CommandService:
    """Run confirmed commands through the configured execution backend."""

    def __init__(
        self,
        config: CommandConfig | None = None,
        store: CommandStore | None = None,
        policy: CommandPolicy | None = None,
        ssm_client: Any | None = None,
    ) -> None:
        self.config = config or CommandConfig.from_environment()
        self.store = store or CommandStore(
            sqlite_path=self.config.state_path,
            confirmation_ttl_seconds=self.config.confirmation_ttl_seconds,
        )
        self.policy = policy or CommandPolicy()
        self._ssm_client = ssm_client

    def run_sync(
        self,
        owner_sub: str,
        command: str | None = None,
        confirmation_id: str | None = None,
        confirmation_token: str | None = None,
    ) -> CommandOutcome:
        """Run once, returning immediately or preserving an in-progress job."""
        authorized_command, confirmation = self._authorize_command(
            owner_sub,
            command,
            _SYNC_MODE,
            confirmation_id,
            confirmation_token,
        )
        if confirmation is not None:
            return confirmation
        assert authorized_command is not None

        job = self._start_job(owner_sub, authorized_command, _SYNC_MODE)
        deadline = time.monotonic() + self.config.sync_wait_seconds
        while time.monotonic() < deadline:
            current = self._refresh_job(owner_sub, job.job_id)
            if current.status in TERMINAL_JOB_STATUSES:
                return self._outcome_from_job(current)
            time.sleep(self.config.poll_interval_seconds)

        current = self._refresh_job(owner_sub, job.job_id)
        return self._outcome_from_job(current)

    def start_async(
        self,
        owner_sub: str,
        command: str | None = None,
        confirmation_id: str | None = None,
        confirmation_token: str | None = None,
    ) -> CommandOutcome:
        """Start one command once and return its durable owner-scoped job ID."""
        authorized_command, confirmation = self._authorize_command(
            owner_sub,
            command,
            _ASYNC_MODE,
            confirmation_id,
            confirmation_token,
        )
        if confirmation is not None:
            return confirmation
        assert authorized_command is not None

        job = self._start_job(owner_sub, authorized_command, _ASYNC_MODE)
        return self._outcome_from_job(job)

    def get_async_result(self, owner_sub: str, job_id: str) -> CommandOutcome:
        """Return current result only for the job's authenticated owner."""
        self._require_owner(owner_sub)
        if not isinstance(job_id, str) or not job_id.strip():
            raise ValueError("job_id must be a non-empty string")

        job = self.store.get_job(owner_sub, job_id)
        if job is None:
            return CommandOutcome(
                status="not_found",
                job_id=job_id,
                message="command job was not found for the authenticated user",
            )

        return self._outcome_from_job(self._refresh_job(owner_sub, job_id))

    def _authorize_command(
        self,
        owner_sub: str,
        command: str | None,
        execution_mode: str,
        confirmation_id: str | None,
        confirmation_token: str | None,
    ) -> tuple[str | None, CommandOutcome | None]:
        self._require_owner(owner_sub)
        has_confirmation_id = confirmation_id is not None
        has_confirmation_token = confirmation_token is not None
        if command is not None and (has_confirmation_id or has_confirmation_token):
            raise ValueError(
                "command cannot be combined with confirmation_id or "
                "confirmation_token"
            )
        if command is None:
            if not has_confirmation_id or not has_confirmation_token:
                raise ValueError(
                    "provide command, or provide both confirmation_id and "
                    "confirmation_token"
                )
            confirmed_command = self.store.consume_confirmation(
                owner_sub,
                confirmation_id,
                confirmation_token,
                execution_mode,
            )
            if confirmed_command is None:
                raise ValueError(
                    "confirmation is invalid, expired, already used, or for "
                    "a different execution mode"
                )
            return confirmed_command, None

        clean_command = self._require_command(command)
        decision = self.policy.classify(
            clean_command,
            confirmation_profile=self.config.confirmation_profile,
        )
        if not decision.confirmation_required:
            return clean_command, None

        pending = self.store.issue_confirmation(
            owner_sub,
            clean_command,
            execution_mode,
            decision.reason,
        )
        return (
            None,
            CommandOutcome(
                status="confirmation_required",
                confirmation_required=True,
                confirmation_id=pending.confirmation_id,
                confirmation_token=pending.confirmation_token,
                message=decision.reason,
            ),
        )

    def _start_job(
        self,
        owner_sub: str,
        command: str,
        execution_mode: str,
    ) -> StoredCommandJob:
        clean_command = self._require_command(command)
        job = self.store.create_job(
            owner_sub=owner_sub,
            command=clean_command,
            execution_mode=execution_mode,
            backend=self.config.backend,
            working_directory=str(self.config.working_directory),
            shell_executable=self.config.shell_executable,
            command_timeout_seconds=self.config.command_timeout_seconds,
            max_output_bytes=self.config.max_output_bytes,
        )

        try:
            if self.config.backend == "local":
                backend_job_id = self._start_local_worker(job.job_id)
            else:
                backend_job_id = self._send_ssm_command(clean_command)
            self.store.update_backend_job(job.job_id, backend_job_id)
        except Exception as error:
            self.store.complete_job(
                job.job_id,
                "failed",
                None,
                "",
                "command backend could not start the job",
                False,
            )
            raise CommandServiceError(
                "command backend could not start the job"
            ) from error

        refreshed = self.store.get_job(owner_sub, job.job_id)
        assert refreshed is not None
        return refreshed

    def _refresh_job(self, owner_sub: str, job_id: str) -> StoredCommandJob:
        job = self.store.get_job(owner_sub, job_id)
        if job is None:
            raise CommandServiceError("command job state is unavailable")
        if job.status in TERMINAL_JOB_STATUSES:
            return job

        try:
            if job.backend == "ssm":
                self._refresh_ssm_job(job)
            else:
                self._refresh_local_job(job)
        except Exception as error:
            raise CommandServiceError(
                "command backend could not retrieve the job result"
            ) from error

        refreshed = self.store.get_job(owner_sub, job_id)
        if refreshed is None:
            raise CommandServiceError("command job state is unavailable")
        return refreshed

    def _start_local_worker(self, job_id: str) -> str:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "ragstream.cli.command_service",
                "--local-worker",
                str(self.store.sqlite_path.resolve()),
                job_id,
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return str(process.pid)

    def _send_ssm_command(self, command: str) -> str:
        client = self._get_ssm_client()
        response = client.send_command(
            InstanceIds=[self.config.target_instance_id],
            DocumentName="AWS-RunShellScript",
            Comment="GHOST MCP CLI command",
            Parameters={
                "commands": [command],
                "executionTimeout": [str(self.config.command_timeout_seconds)],
            },
        )
        command_id = response.get("Command", {}).get("CommandId")
        if not isinstance(command_id, str) or not command_id:
            raise RuntimeError("SSM did not return a command identifier")
        return command_id

    def _refresh_local_job(self, job: StoredCommandJob) -> None:
        if not job.backend_job_id:
            return
        try:
            os.kill(int(job.backend_job_id), 0)
        except ProcessLookupError:
            latest = self.store.get_job_for_worker(job.job_id)
            if latest is not None and latest.status not in TERMINAL_JOB_STATUSES:
                self.store.complete_job(
                    job.job_id,
                    "failed",
                    None,
                    "",
                    "local command worker ended without a result",
                    False,
                )
        except PermissionError:
            return

    def _refresh_ssm_job(self, job: StoredCommandJob) -> None:
        if not job.backend_job_id:
            return
        try:
            response = self._get_ssm_client().get_command_invocation(
                CommandId=job.backend_job_id,
                InstanceId=self.config.target_instance_id,
            )
        except Exception as error:
            if _aws_error_code(error) == "InvocationDoesNotExist":
                return
            raise

        ssm_status = str(response.get("Status", ""))
        if ssm_status in _SSM_IN_PROGRESS_STATUSES:
            return

        stdout, stdout_truncated = _truncate_text(
            str(response.get("StandardOutputContent", "")),
            job.max_output_bytes,
        )
        stderr, stderr_truncated = _truncate_text(
            str(response.get("StandardErrorContent", "")),
            job.max_output_bytes,
        )
        exit_code_value = response.get("ResponseCode")
        exit_code = (
            int(exit_code_value)
            if isinstance(exit_code_value, int) and exit_code_value >= 0
            else None
        )
        status = _map_ssm_status(ssm_status, exit_code)
        self.store.complete_job(
            job.job_id,
            status,
            exit_code,
            stdout,
            stderr,
            stdout_truncated or stderr_truncated,
        )

    def _get_ssm_client(self) -> Any:
        if self._ssm_client is None:
            try:
                import boto3
            except ImportError as error:
                raise RuntimeError("boto3 is required for the SSM backend") from error
            self._ssm_client = boto3.client(
                "ssm",
                region_name=self.config.aws_region,
            )
        return self._ssm_client

    @staticmethod
    def _outcome_from_job(job: StoredCommandJob) -> CommandOutcome:
        return CommandOutcome(
            status=job.status,
            exit_code=job.exit_code,
            stdout=job.stdout,
            stderr=job.stderr,
            truncated=job.truncated,
            job_id=job.job_id,
        )

    @staticmethod
    def _require_owner(owner_sub: str) -> None:
        if not isinstance(owner_sub, str) or not owner_sub.strip():
            raise ValueError("owner_sub must be a non-empty string")

    @staticmethod
    def _require_command(command: str) -> str:
        if not isinstance(command, str) or not command.strip():
            raise ValueError("command must be a non-empty string")
        clean_command = command.strip()
        if len(clean_command) > MAX_COMMAND_CHARACTERS:
            raise ValueError(
                f"command must not exceed {MAX_COMMAND_CHARACTERS} characters"
            )
        return clean_command


def _run_local_worker(sqlite_path: Path, job_id: str) -> int:
    """Execute one persisted local job in a detached interpreter process."""
    store = CommandStore(sqlite_path=sqlite_path)
    job = store.get_job_for_worker(job_id)
    if job is None or job.backend != "local":
        return 2

    try:
        completed = subprocess.run(
            [job.shell_executable, "-lc", job.command],
            cwd=job.working_directory,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=job.command_timeout_seconds,
            check=False,
        )
        stdout, stdout_truncated = _truncate_bytes(
            completed.stdout,
            job.max_output_bytes,
        )
        stderr, stderr_truncated = _truncate_bytes(
            completed.stderr,
            job.max_output_bytes,
        )
        status = "succeeded" if completed.returncode == 0 else "failed"
        store.complete_job(
            job.job_id,
            status,
            completed.returncode,
            stdout,
            stderr,
            stdout_truncated or stderr_truncated,
        )
    except subprocess.TimeoutExpired as error:
        stdout, stdout_truncated = _truncate_bytes(
            error.stdout or b"",
            job.max_output_bytes,
        )
        stderr, stderr_truncated = _truncate_bytes(
            error.stderr or b"",
            job.max_output_bytes,
        )
        timeout_message = "command exceeded its configured execution timeout"
        stderr = f"{stderr}\n{timeout_message}".strip()
        store.complete_job(
            job.job_id,
            "timed_out",
            None,
            stdout,
            stderr,
            stdout_truncated or stderr_truncated,
        )
    except Exception:  # noqa: BLE001 - sanitize the detached worker boundary
        store.complete_job(
            job.job_id,
            "failed",
            None,
            "",
            "local command execution failed",
            False,
        )
        return 1

    return 0


def _truncate_bytes(value: bytes, limit: int) -> tuple[str, bool]:
    truncated = len(value) > limit
    selected = value[:limit] if truncated else value
    return selected.decode("utf-8", errors="replace"), truncated


def _truncate_text(value: str, limit: int) -> tuple[str, bool]:
    return _truncate_bytes(value.encode("utf-8"), limit)


def _map_ssm_status(ssm_status: str, exit_code: int | None) -> str:
    if ssm_status == "Success" and exit_code == 0:
        return "succeeded"
    if ssm_status == "Cancelled":
        return "cancelled"
    if ssm_status in _SSM_TIMED_OUT_STATUSES:
        return "timed_out"
    return "failed"


def _aws_error_code(error: Exception) -> str | None:
    response = getattr(error, "response", None)
    if not isinstance(response, dict):
        return None
    error_data = response.get("Error")
    if not isinstance(error_data, dict):
        return None
    code = error_data.get("Code")
    return str(code) if code is not None else None


def _environment_int(name: str, default: int) -> int:
    value = os.getenv(name)
    return int(value) if value is not None else default


def _environment_float(name: str, default: float) -> float:
    value = os.getenv(name)
    return float(value) if value is not None else default


def _main(arguments: list[str]) -> int:
    if len(arguments) != 3 or arguments[0] != "--local-worker":
        return 2
    return _run_local_worker(Path(arguments[1]), arguments[2])


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
