"""Test the Part 1 CLI policy, state, and execution service."""

from __future__ import annotations

import shlex
import sqlite3
import time
from pathlib import Path
from typing import Any

import pytest

from ragstream.cli.command_policy import CommandPolicy
from ragstream.cli.command_service import (
    CommandConfig,
    CommandService,
    CommandServiceError,
)
from ragstream.cli.command_store import CommandStore


class FakeSsmClient:
    """Return controlled SSM responses without contacting AWS."""

    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self.responses = list(responses)
        self.sent: list[dict[str, Any]] = []

    def send_command(self, **request: Any) -> dict[str, Any]:
        self.sent.append(request)
        return {"Command": {"CommandId": "ssm-command-1"}}

    def get_command_invocation(self, **request: Any) -> dict[str, Any]:
        del request
        if len(self.responses) > 1:
            return self.responses.pop(0)
        return self.responses[0]


class FailingSsmClient:
    """Raise a backend detail that must not cross the service boundary."""

    def send_command(self, **request: Any) -> dict[str, Any]:
        del request
        raise RuntimeError("secret backend diagnostic")


def _local_service(
    tmp_path: Path,
    *,
    sync_wait_seconds: float = 2.0,
    max_output_bytes: int = 65_536,
) -> CommandService:
    config = CommandConfig(
        backend="local",
        state_path=tmp_path / "command_state.sqlite3",
        working_directory=tmp_path,
        sync_wait_seconds=sync_wait_seconds,
        poll_interval_seconds=0.01,
        max_output_bytes=max_output_bytes,
        command_timeout_seconds=5,
        confirmation_profile="strict",
    )
    return CommandService(config=config)


def _wait_for_terminal_result(
    service: CommandService,
    owner_sub: str,
    job_id: str,
) -> Any:
    deadline = time.monotonic() + 5
    result = service.get_async_result(owner_sub, job_id)
    while result.status == "in_progress" and time.monotonic() < deadline:
        time.sleep(0.02)
        result = service.get_async_result(owner_sub, job_id)
    return result


@pytest.mark.parametrize(
    "command",
    [
        "ls -la",
        "df -h",
        "docker ps",
        "docker logs ghost-mcp --tail 100",
        "git status",
        "journalctl -u docker --since '10 minutes ago' --no-pager",
        "systemctl status docker --no-pager",
        "cd /tmp && sed -n '1,20p' file.txt",
        "cat file.txt | head -n 5",
        "find /tmp -maxdepth 1 -type f -print",
    ],
)
def test_read_only_commands_do_not_require_confirmation(command: str) -> None:
    decision = CommandPolicy().classify(command)

    assert decision.confirmation_required is False


@pytest.mark.parametrize(
    "command",
    [
        "rm -f old.log",
        "printf changed > config.ini",
        "git push origin main",
        "docker restart ghost-mcp",
        'python -c \'open("file", "w").write("x")\'',
        "journalctl --vacuum-time=1d",
        "env rm -f old.log",
        "sed -i 's/old/new/' config.ini",
    ],
)
def test_mutating_or_uncertain_commands_require_confirmation(
    command: str,
) -> None:
    decision = CommandPolicy().classify(command)

    assert decision.confirmation_required is True
    assert decision.reason


def test_confirmation_is_owner_scoped_exact_and_one_time(tmp_path: Path) -> None:
    store = CommandStore(tmp_path / "state.sqlite3")
    pending = store.issue_confirmation(
        "owner-1",
        "rm -f old.log",
        "synchronous",
        "rm can delete files",
    )

    assert store.consume_confirmation(
        "owner-2",
        pending.confirmation_id,
        pending.confirmation_token,
        "synchronous",
    ) is None
    assert store.consume_confirmation(
        "owner-1",
        pending.confirmation_id,
        pending.confirmation_token,
        "asynchronous",
    ) is None
    assert store.consume_confirmation(
        "owner-1",
        pending.confirmation_id,
        pending.confirmation_token,
        "synchronous",
    ) == "rm -f old.log"
    assert store.consume_confirmation(
        "owner-1",
        pending.confirmation_id,
        pending.confirmation_token,
        "synchronous",
    ) is None


def test_confirmation_schema_migrates_existing_database(tmp_path: Path) -> None:
    state_path = tmp_path / "legacy.sqlite3"

    with sqlite3.connect(state_path) as connection:
        connection.execute(
            """
            CREATE TABLE cli_confirmations (
                token_digest TEXT PRIMARY KEY,
                owner_sub TEXT NOT NULL,
                command TEXT NOT NULL,
                execution_mode TEXT NOT NULL,
                reason TEXT NOT NULL,
                expires_at_epoch REAL NOT NULL
            )
            """
        )

    CommandStore(state_path)
    with sqlite3.connect(state_path) as connection:
        columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(cli_confirmations)"
            )
        }

    assert "confirmation_id" in columns


def test_job_state_is_durable_and_owner_scoped(tmp_path: Path) -> None:
    state_path = tmp_path / "state.sqlite3"
    first_store = CommandStore(state_path)
    job = first_store.create_job(
        owner_sub="owner-1",
        command="df -h",
        execution_mode="asynchronous",
        backend="ssm",
        working_directory=str(tmp_path),
        shell_executable="/bin/bash",
        command_timeout_seconds=60,
        max_output_bytes=1024,
        backend_job_id="ssm-1",
    )

    second_store = CommandStore(state_path)

    assert second_store.get_job("owner-1", job.job_id) == job
    assert second_store.get_job("owner-2", job.job_id) is None


def test_local_sync_returns_stdout_stderr_and_exit_code(tmp_path: Path) -> None:
    service = _local_service(tmp_path)

    success = service.run_sync("owner-1", "printf 'hello'")
    failure = service.run_sync(
        "owner-1",
        "printf 'problem' >&2; exit 7",
    )

    assert success.status == "succeeded"
    assert success.exit_code == 0
    assert success.stdout == "hello"
    assert success.stderr == ""
    assert failure.confirmation_required is True

    confirmed = service.run_sync(
        "owner-1",
        confirmation_id=failure.confirmation_id,
        confirmation_token=failure.confirmation_token,
    )
    assert confirmed.status == "failed"
    assert confirmed.exit_code == 7
    assert confirmed.stderr == "problem"


def test_exact_confirmation_executes_the_stored_request(tmp_path: Path) -> None:
    service = _local_service(tmp_path)
    output_path = tmp_path / "confirmed.txt"
    command = f"printf 'changed' > {shlex.quote(str(output_path))}"

    first = service.run_sync("owner-1", command)

    assert first.status == "confirmation_required"
    assert first.confirmation_id
    assert first.confirmation_token
    assert not output_path.exists()

    second = service.run_sync(
        "owner-1",
        confirmation_id=first.confirmation_id,
        confirmation_token=first.confirmation_token,
    )

    assert second.status == "succeeded"
    assert output_path.read_text(encoding="utf-8") == "changed"


def test_trusted_local_confirms_only_dangerous_commands(tmp_path: Path) -> None:
    service = CommandService(
        config=CommandConfig(
            backend="local",
            state_path=tmp_path / "trusted.sqlite3",
            working_directory=tmp_path,
            poll_interval_seconds=0.01,
            confirmation_profile="trusted_local",
        )
    )

    normal = service.run_sync("owner-1", "mkdir ordinary-folder")
    dangerous = service.run_sync("owner-1", "rm -rf ordinary-folder")

    assert normal.status == "succeeded"
    assert dangerous.status == "confirmation_required"
    assert dangerous.confirmation_id


def test_auto_profile_uses_trusted_local_and_strict_ssm(tmp_path: Path) -> None:
    local = CommandConfig(working_directory=tmp_path)
    remote = CommandConfig(
        backend="ssm",
        target_instance_id="i-fixed",
        working_directory=tmp_path,
    )

    assert local.confirmation_profile == "trusted_local"
    assert remote.confirmation_profile == "strict"


def test_local_output_is_truncated_with_an_explicit_flag(tmp_path: Path) -> None:
    service = _local_service(tmp_path, max_output_bytes=5)

    result = service.run_sync("owner-1", "printf '1234567890'")

    assert result.status == "succeeded"
    assert result.stdout == "12345"
    assert result.truncated is True


def test_sync_timeout_preserves_the_same_job_for_later_result(
    tmp_path: Path,
) -> None:
    service = _local_service(tmp_path, sync_wait_seconds=0.03)

    started = service.run_sync("owner-1", "sleep 0.15; printf 'done'")

    assert started.status == "in_progress"
    assert started.job_id

    completed = _wait_for_terminal_result(
        service,
        "owner-1",
        started.job_id,
    )
    assert completed.status == "succeeded"
    assert completed.stdout == "done"


def test_async_result_is_hidden_from_another_owner(tmp_path: Path) -> None:
    service = _local_service(tmp_path)
    started = service.start_async("owner-1", "printf 'done'")
    assert started.job_id

    hidden = service.get_async_result("owner-2", started.job_id)
    visible = _wait_for_terminal_result(service, "owner-1", started.job_id)

    assert hidden.status == "not_found"
    assert visible.status == "succeeded"
    assert visible.stdout == "done"


def test_ssm_backend_targets_only_the_configured_instance(tmp_path: Path) -> None:
    client = FakeSsmClient(
        [
            {"Status": "InProgress", "ResponseCode": -1},
            {
                "Status": "Success",
                "ResponseCode": 0,
                "StandardOutputContent": "host output",
                "StandardErrorContent": "",
            },
        ]
    )
    service = CommandService(
        config=CommandConfig(
            backend="ssm",
            state_path=tmp_path / "state.sqlite3",
            target_instance_id="i-fixed",
            working_directory=tmp_path,
            poll_interval_seconds=0.01,
        ),
        ssm_client=client,
    )

    started = service.start_async("owner-1", "df -h")
    running = service.get_async_result("owner-1", started.job_id or "")
    completed = service.get_async_result("owner-1", started.job_id or "")

    assert client.sent[0]["InstanceIds"] == ["i-fixed"]
    assert client.sent[0]["DocumentName"] == "AWS-RunShellScript"
    assert running.status == "in_progress"
    assert completed.status == "succeeded"
    assert completed.stdout == "host output"


def test_backend_exception_is_sanitized(tmp_path: Path) -> None:
    service = CommandService(
        config=CommandConfig(
            backend="ssm",
            state_path=tmp_path / "state.sqlite3",
            target_instance_id="i-fixed",
            working_directory=tmp_path,
        ),
        ssm_client=FailingSsmClient(),
    )

    with pytest.raises(CommandServiceError) as raised:
        service.start_async("owner-1", "df -h")

    assert "secret backend diagnostic" not in str(raised.value)
    assert str(raised.value) == "command backend could not start the job"


def test_environment_selects_backend_without_code_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GHOST_CLI_BACKEND", "ssm")
    monkeypatch.setenv("GHOST_CLI_TARGET_INSTANCE_ID", "i-fixed")
    monkeypatch.setenv("GHOST_CLI_STATE_PATH", str(tmp_path / "state.sqlite3"))
    monkeypatch.setenv("GHOST_CLI_WORKING_DIRECTORY", str(tmp_path))

    config = CommandConfig.from_environment()

    assert config.backend == "ssm"
    assert config.target_instance_id == "i-fixed"
    assert config.confirmation_profile == "strict"
