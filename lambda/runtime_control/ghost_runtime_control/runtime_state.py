"""Read and persist the small SSM-backed state used by Runtime Control.

The module owns runtime-state storage and validation; it does not control EC2.

Main classes:
    RuntimeState:
        Immutable snapshot used by status reporting and the idle watchdog.
    RuntimeStateStore:
        Reads state and initializes the state for a new EC2 run.

Main methods:
    RuntimeStateStore.load():
        Returns one validated snapshot from the configured SSM parameters.
    RuntimeStateStore.initialize_run():
        Persists the profile, timeout, activity time, and zero active calls.

Important notes:
    State values are non-secret strings. SSM failures propagate to the Lambda
    boundary, where they can be logged and converted to a sanitized response.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import boto3

from .config import RuntimeControlConfig


# Requirements:
# GHOST-AWS-TGT-EC2-CONTROL-STATE
# GHOST-AWS-TGT-EC2-START-SEQUENCE
# GHOST-AWS-TGT-EC2-LAMBDA-WATCHDOG
# GHOST-MCP-RUNTIME-IDLE-POLICY
# GHOST-MCP-RUNTIME-INFLIGHT


class RuntimeStateError(ValueError):
    """Indicates missing or invalid persisted runtime-control state."""


@dataclass(frozen=True, slots=True)
class RuntimeState:
    """Validated snapshot of the current runtime-control state."""

    effective_idle_timeout_minutes: int
    last_activity_epoch: int
    active_tool_calls: int
    runtime_profile: int

    def inactivity_seconds(self, now_epoch: int | None = None) -> int | None:
        """Return elapsed inactivity, or None before activity is initialized."""

        if self.last_activity_epoch == 0:
            return None

        current_epoch = int(time.time()) if now_epoch is None else now_epoch
        return max(0, current_epoch - self.last_activity_epoch)

    def idle_timeout_reached(self, now_epoch: int | None = None) -> bool:
        """Return whether inactivity reached the timeout with no active calls."""

        if self.active_tool_calls > 0:
            return False

        inactivity_seconds = self.inactivity_seconds(now_epoch)
        if inactivity_seconds is None:
            return False

        timeout_seconds = self.effective_idle_timeout_minutes * 60
        return inactivity_seconds >= timeout_seconds


class RuntimeStateStore:
    """Owns validated reads and initialization of SSM runtime state."""

    def __init__(
        self,
        config: RuntimeControlConfig,
        ssm_client: Any | None = None,
    ) -> None:
        self._config = config
        self._ssm_client = ssm_client or boto3.client("ssm")

    def load(self) -> RuntimeState:
        """Load all configured state parameters as one validated snapshot."""

        parameter_names = self._parameter_names()

        response = self._ssm_client.get_parameters(
            Names=list(parameter_names.values()),
            WithDecryption=False,
        )

        invalid_parameters = response.get("InvalidParameters", [])
        if invalid_parameters:
            missing_names = ", ".join(sorted(invalid_parameters))
            raise RuntimeStateError(
                f"Missing runtime-control SSM parameters: {missing_names}."
            )

        values_by_name = {
            parameter["Name"]: parameter["Value"]
            for parameter in response.get("Parameters", [])
        }

        missing_names = sorted(
            set(parameter_names.values()) - values_by_name.keys()
        )
        if missing_names:
            raise RuntimeStateError(
                "SSM returned an incomplete runtime-control state: "
                + ", ".join(missing_names)
                + "."
            )

        idle_timeout = self._parse_integer(
            values_by_name[parameter_names["idle_timeout"]],
            parameter_names["idle_timeout"],
            minimum=self._config.min_idle_timeout_minutes,
            maximum=self._config.max_idle_timeout_minutes,
        )

        last_activity = self._parse_integer(
            values_by_name[parameter_names["last_activity"]],
            parameter_names["last_activity"],
            minimum=0,
        )

        active_calls = self._parse_integer(
            values_by_name[parameter_names["active_calls"]],
            parameter_names["active_calls"],
            minimum=0,
        )

        runtime_profile = self._parse_integer(
            values_by_name[parameter_names["runtime_profile"]],
            parameter_names["runtime_profile"],
            minimum=1,
            maximum=2,
        )

        return RuntimeState(
            effective_idle_timeout_minutes=idle_timeout,
            last_activity_epoch=last_activity,
            active_tool_calls=active_calls,
            runtime_profile=runtime_profile,
        )

    def initialize_run(
        self,
        runtime_profile: int,
        idle_timeout_minutes: int,
        now_epoch: int | None = None,
    ) -> RuntimeState:
        """Persist the complete initial state before starting the EC2 instance."""

        if runtime_profile not in (1, 2):
            raise ValueError("runtime_profile must be 1 or 2.")

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

        activity_epoch = int(time.time()) if now_epoch is None else now_epoch
        if activity_epoch <= 0:
            raise ValueError("now_epoch must be greater than zero.")

        parameter_names = self._parameter_names()

        # The instance remains stopped until all writes succeed. Writing the
        # activity timestamp last makes it the final marker of initialization.
        self._put(
            parameter_names["runtime_profile"],
            runtime_profile,
        )
        self._put(
            parameter_names["idle_timeout"],
            idle_timeout_minutes,
        )
        self._put(
            parameter_names["active_calls"],
            0,
        )
        self._put(
            parameter_names["last_activity"],
            activity_epoch,
        )

        return RuntimeState(
            effective_idle_timeout_minutes=idle_timeout_minutes,
            last_activity_epoch=activity_epoch,
            active_tool_calls=0,
            runtime_profile=runtime_profile,
        )

    def _parameter_names(self) -> dict[str, str]:
        return {
            "idle_timeout": self._config.ssm_idle_timeout_parameter,
            "last_activity": self._config.ssm_last_activity_parameter,
            "active_calls": self._config.ssm_active_calls_parameter,
            "runtime_profile": self._config.ssm_runtime_profile_parameter,
        }

    def _put(self, parameter_name: str, value: int) -> None:
        self._ssm_client.put_parameter(
            Name=parameter_name,
            Type="String",
            Value=str(value),
            Overwrite=True,
        )

    @staticmethod
    def _parse_integer(
        raw_value: str,
        parameter_name: str,
        *,
        minimum: int,
        maximum: int | None = None,
    ) -> int:
        try:
            value = int(raw_value)
        except (TypeError, ValueError) as error:
            raise RuntimeStateError(
                f"SSM parameter {parameter_name!r} must contain an integer."
            ) from error

        if value < minimum or (
            maximum is not None and value > maximum
        ):
            expected_range = (
                f"{minimum} or greater"
                if maximum is None
                else f"between {minimum} and {maximum}"
            )
            raise RuntimeStateError(
                f"SSM parameter {parameter_name!r} must be {expected_range}."
            )

        return value