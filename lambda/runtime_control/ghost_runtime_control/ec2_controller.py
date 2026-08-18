"""Control the lifecycle of the one configured GHOST EC2 instance.

The module owns EC2 inspection, approved profile changes, start readiness,
explicit stop, and watchdog stop decisions. Authentication and MCP protocol
handling remain outside this module.

Main classes:
    RuntimeStatus:
        Immutable observation returned by lifecycle and status operations.
    StartResult:
        Reports whether start was performed and includes the resulting status.
    Ec2Controller:
        Coordinates EC2 operations, runtime state, and GHOST health checks.

Main methods:
    Ec2Controller.start():
        Applies an approved profile to a stopped instance and starts GHOST.
    Ec2Controller.status():
        Reports current EC2, readiness, and inactivity information.
    Ec2Controller.stop():
        Safely stops the instance without changing its profile.
    Ec2Controller.stop_if_idle():
        Stops a running instance only when the persisted idle policy allows it.

Important notes:
    The target instance ID comes only from deployment configuration. The class
    never terminates an instance and never accepts an arbitrary AWS resource.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import boto3

from .config import RuntimeControlConfig
from .runtime_state import RuntimeState, RuntimeStateStore


# Requirements:
# GHOST-MCP-RUNTIME-FIXED-TARGET
# GHOST-MCP-RUNTIME-START-STOPPED-ONLY
# GHOST-MCP-RUNTIME-START-READINESS
# GHOST-MCP-RUNTIME-STATUS-NO-ACTIVITY
# GHOST-MCP-RUNTIME-STOP-SAFE
# GHOST-AWS-TGT-EC2-PROFILE-WHILE-STOPPED
# GHOST-AWS-TGT-EC2-LAMBDA-WATCHDOG


# EC2 and health readiness are checked every five seconds during startup.
_POLL_INTERVAL_SECONDS = 5

# A single health request must fail quickly enough to continue bounded polling.
_HEALTH_REQUEST_TIMEOUT_SECONDS = 5

# StopInstances is used only for states from which a normal stop is meaningful.
_STOPPABLE_STATES = frozenset({"pending", "running"})


class Ec2ControlError(RuntimeError):
    """Indicates that a lifecycle operation cannot be completed safely."""


@dataclass(frozen=True, slots=True)
class RuntimeStatus:
    """Current EC2 and GHOST runtime state returned to higher layers."""

    # AWS lifecycle state: stopped, pending, running, stopping, and so on.
    ec2_state: str

    # Concrete EC2 instance type currently configured on the fixed instance.
    instance_type: str

    # Profile 1 or 2 when the current type is approved; otherwise None.
    runtime_profile: int | None

    # True only after the configured GHOST health endpoint returns HTTP 2xx.
    ghost_ready: bool

    # Per-run timeout stored in SSM and used by both idle watchdogs.
    effective_idle_timeout_minutes: int

    # Seconds since qualifying GHOST activity, or None before initialization.
    inactivity_seconds: int | None

    # Number of qualifying GHOST tool calls currently reported as executing.
    active_tool_calls: int


@dataclass(frozen=True, slots=True)
class StartResult:
    """Result of a start request, including explicit no-change information."""

    # False when EC2 was not stopped and no start or profile change was made.
    started: bool

    # Complete runtime observation after the start attempt.
    status: RuntimeStatus

    # Short explanation suitable for conversion to an MCP tool result.
    message: str


class Ec2Controller:
    """Control the fixed GHOST EC2 instance and its idle-shutdown policy."""

    def __init__(
        self,
        config: RuntimeControlConfig,
        state_store: RuntimeStateStore,
        ec2_client: Any | None = None,
        health_url_opener: Any | None = None,
    ) -> None:
        # Configuration fixes the target instance, profiles, limits, and URL.
        self._config = config

        # The state store owns the four non-secret SSM runtime values.
        self._state_store = state_store

        # Production uses the Lambda runtime's boto3 EC2 client.
        # A supplied client allows focused testing without contacting AWS.
        self._ec2_client = ec2_client or boto3.client("ec2")

        # Production uses urllib for the HTTPS health request.
        # A supplied opener allows readiness tests without network calls.
        self._health_url_opener = health_url_opener or urlopen

    def start(
        self,
        runtime_profile: int | None = None,
        idle_timeout_minutes: int | None = None,
    ) -> StartResult:
        """Start the stopped instance and wait for real GHOST readiness."""

        selected_profile = (
            self._config.default_profile
            if runtime_profile is None
            else runtime_profile
        )

        selected_timeout = (
            self._config.default_idle_timeout_minutes
            if idle_timeout_minutes is None
            else idle_timeout_minutes
        )

        # instance_type_for accepts only profile 1 or 2.
        desired_instance_type = self._config.instance_type_for(
            selected_profile
        )
        self._validate_idle_timeout(selected_timeout)

        instance = self._describe_instance()
        observed_state = instance["State"]["Name"]

        # Changing a running instance type would require an implicit stop and
        # restart. The approved workflow therefore makes no change unless the
        # instance is already stopped.
        if observed_state != "stopped":
            status = self._build_status(
                instance=instance,
                runtime_state=self._state_store.load(),
                check_readiness=observed_state == "running",
            )

            return StartResult(
                started=False,
                status=status,
                message=(
                    f"No change was made because EC2 is {observed_state!r}; "
                    "runtime profile changes and start are allowed only from "
                    "the stopped state."
                ),
            )

        # The instance type is changed only when necessary and only while the
        # instance is stopped.
        if instance["InstanceType"] != desired_instance_type:
            self._ec2_client.modify_instance_attribute(
                InstanceId=self._config.managed_instance_id,
                InstanceType={"Value": desired_instance_type},
            )

        # The independent local watchdog performs an operating-system
        # shutdown. This setting guarantees that shutdown means stop,
        # never terminate.
        self._ec2_client.modify_instance_attribute(
            InstanceId=self._config.managed_instance_id,
            InstanceInitiatedShutdownBehavior={"Value": "stop"},
        )

        # Runtime state is initialized before StartInstances. Therefore, an
        # accidentally started but unused instance is protected immediately.
        runtime_state = self._state_store.initialize_run(
            runtime_profile=selected_profile,
            idle_timeout_minutes=selected_timeout,
        )

        self._ec2_client.start_instances(
            InstanceIds=[self._config.managed_instance_id]
        )

        # One deadline bounds the complete AWS-running and GHOST-ready wait.
        startup_deadline = (
            time.monotonic() + self._config.startup_wait_seconds
        )

        instance = self._wait_for_running(startup_deadline)

        ghost_ready = False
        if instance["State"]["Name"] == "running":
            ghost_ready = self._wait_for_ghost_readiness(
                startup_deadline
            )

        # Refresh the AWS observation after the bounded startup sequence.
        # The result therefore never reports an earlier observed state.
        instance = self._describe_instance()

        status = self._build_status(
            instance=instance,
            runtime_state=runtime_state,
            known_readiness=ghost_ready,
        )

        if ghost_ready:
            message = (
                "GHOST EC2 started and application readiness was verified."
            )
        else:
            message = (
                "EC2 start was requested, but GHOST application readiness "
                "was not verified within the configured startup limit."
            )

        return StartResult(
            started=True,
            status=status,
            message=message,
        )

    def status(self) -> RuntimeStatus:
        """Return actual runtime status without refreshing idle activity."""

        instance = self._describe_instance()
        runtime_state = self._state_store.load()

        return self._build_status(
            instance=instance,
            runtime_state=runtime_state,
            check_readiness=instance["State"]["Name"] == "running",
        )

    def stop(self) -> RuntimeStatus:
        """Request a normal idempotent stop without changing the profile."""

        instance = self._describe_instance()
        observed_state = instance["State"]["Name"]

        if observed_state in _STOPPABLE_STATES:
            self._ec2_client.stop_instances(
                InstanceIds=[self._config.managed_instance_id]
            )
            instance = self._describe_instance()

        elif observed_state not in {"stopped", "stopping"}:
            raise Ec2ControlError(
                "The managed EC2 instance cannot be stopped from "
                f"state {observed_state!r}."
            )

        # No runtime profile or timeout value is changed as a side effect.
        return self._build_status(
            instance=instance,
            runtime_state=self._state_store.load(),
            known_readiness=False,
        )

    def stop_if_idle(self) -> RuntimeStatus | None:
        """Stop a running instance only after the idle policy is reached."""

        runtime_state = self._state_store.load()

        # A positive active-call count always prevents watchdog shutdown.
        if not runtime_state.idle_timeout_reached():
            return None

        instance = self._describe_instance()

        # The watchdog does not start, restart, or modify a stopped instance.
        if instance["State"]["Name"] != "running":
            return None

        # Re-read immediately before StopInstances. This prevents an older
        # watchdog snapshot from ignoring newly published activity or calls.
        runtime_state = self._state_store.load()
        if not runtime_state.idle_timeout_reached():
            return None

        self._ec2_client.stop_instances(
            InstanceIds=[self._config.managed_instance_id]
        )

        instance = self._describe_instance()

        return self._build_status(
            instance=instance,
            runtime_state=runtime_state,
            known_readiness=False,
        )

    def _describe_instance(self) -> dict[str, Any]:
        """Return the one configured EC2 instance description."""

        response = self._ec2_client.describe_instances(
            InstanceIds=[self._config.managed_instance_id]
        )

        instances = [
            instance
            for reservation in response.get("Reservations", [])
            for instance in reservation.get("Instances", [])
        ]

        if len(instances) != 1:
            raise Ec2ControlError(
                "AWS did not return exactly one configured GHOST EC2 instance."
            )

        instance = instances[0]

        if "State" not in instance or "InstanceType" not in instance:
            raise Ec2ControlError(
                "AWS returned an incomplete GHOST EC2 instance description."
            )

        return instance

    def _wait_for_running(
        self,
        deadline: float,
    ) -> dict[str, Any]:
        """Wait within the shared deadline until AWS reports running."""

        while True:
            instance = self._describe_instance()
            observed_state = instance["State"]["Name"]

            if observed_state == "running":
                return instance

            # Any unexpected terminal or transitional state ends the wait.
            if observed_state not in {"stopped", "pending"}:
                return instance

            if not self._sleep_before_next_poll(deadline):
                return instance

    def _wait_for_ghost_readiness(
        self,
        deadline: float,
    ) -> bool:
        """Poll the real GHOST health URL until success or deadline."""

        while True:
            if self._ghost_health_check_succeeds():
                return True

            if not self._sleep_before_next_poll(deadline):
                return False

    def _ghost_health_check_succeeds(self) -> bool:
        """Return true only for a successful HTTPS health response."""

        request = Request(
            self._config.readiness_url,
            headers={
                "Accept": "application/json",
                "User-Agent": "GHOST-Runtime-Control/1.0",
            },
            method="GET",
        )

        try:
            with self._health_url_opener(
                request,
                timeout=_HEALTH_REQUEST_TIMEOUT_SECONDS,
            ) as response:
                return 200 <= response.status < 300

        except (HTTPError, URLError, TimeoutError, OSError):
            # A failed request means "not ready"; it does not mean that the
            # EC2 start operation itself failed.
            return False

    def _build_status(
        self,
        instance: dict[str, Any],
        runtime_state: RuntimeState,
        *,
        check_readiness: bool = False,
        known_readiness: bool | None = None,
    ) -> RuntimeStatus:
        """Combine AWS observation, SSM state, and optional readiness."""

        instance_type = instance["InstanceType"]

        if instance_type == self._config.profile_1_instance_type:
            runtime_profile = 1
        elif instance_type == self._config.profile_2_instance_type:
            runtime_profile = 2
        else:
            # Reporting None exposes configuration drift without inventing a
            # third selectable runtime profile.
            runtime_profile = None

        ghost_ready = False

        if known_readiness is not None:
            ghost_ready = known_readiness
        elif check_readiness:
            ghost_ready = self._ghost_health_check_succeeds()

        return RuntimeStatus(
            ec2_state=instance["State"]["Name"],
            instance_type=instance_type,
            runtime_profile=runtime_profile,
            ghost_ready=ghost_ready,
            effective_idle_timeout_minutes=(
                runtime_state.effective_idle_timeout_minutes
            ),
            inactivity_seconds=runtime_state.inactivity_seconds(),
            active_tool_calls=runtime_state.active_tool_calls,
        )

    def _validate_idle_timeout(
        self,
        idle_timeout_minutes: int,
    ) -> None:
        """Enforce the configured inclusive 10-to-120-minute range."""

        if not (
            self._config.min_idle_timeout_minutes
            <= idle_timeout_minutes
            <= self._config.max_idle_timeout_minutes
        ):
            raise ValueError(
                "idle_timeout_minutes must be between "
                f"{self._config.min_idle_timeout_minutes} and "
                f"{self._config.max_idle_timeout_minutes}."
            )

    @staticmethod
    def _sleep_before_next_poll(deadline: float) -> bool:
        """Sleep until the next poll without exceeding the shared deadline."""

        remaining_seconds = deadline - time.monotonic()

        if remaining_seconds <= 0:
            return False

        time.sleep(
            min(
                _POLL_INTERVAL_SECONDS,
                remaining_seconds,
            )
        )
        return True