"""Owner-scoped persistent settings for the GHOST prompt builder.

The settings service is deliberately independent from MCP tool registration.
Part 3 can expose these methods through a thin public tool without duplicating
the storage, validation, locking, or atomic-write behavior implemented here.
"""

from __future__ import annotations

import copy
import fcntl
import json
import os
import re
import tempfile

from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Mapping, TextIO

from ragstream.mcp.mcp_tool_contracts import (
    DEFAULT_REQUIRED_SCOPE,
    GhostToolResult,
)
from ragstream.mcp.memory_tool_instructions import (
    load_memory_tool_instructions,
)


DEFAULT_PROMPT_SETTINGS_ROOT = (
    Path(__file__).resolve().parents[2]
    / "data"
    / "mcp"
    / "prompt_settings"
)

ENRICHMENT_FLAG_KEYS = (
    "input_cleanup",
    "prompt_shaping",
    "document_retrieval",
    "memory_retrieval",
    "knowledge_retrieval",
    "general_skill_retrieval",
)
BOOLEAN_SETTING_KEYS = (*ENRICHMENT_FLAG_KEYS, "memory_recency_enabled")
PATH_SETTING_KEYS = ("default_project_name", "default_ragmem_path")
SUPPORTED_SETTING_KEYS = frozenset((*BOOLEAN_SETTING_KEYS, *PATH_SETTING_KEYS))

DEFAULT_PROMPT_SETTINGS: dict[str, Any] = {
    "input_cleanup": False,
    "prompt_shaping": True,
    "document_retrieval": False,
    "memory_retrieval": False,
    "knowledge_retrieval": False,
    "general_skill_retrieval": False,
    "memory_recency_enabled": True,
    "default_project_name": None,
    "default_ragmem_path": None,
}

_SAFE_PATH_PART = re.compile(r"^[A-Za-z0-9._-]+$")


class PromptSettingsError(ValueError):
    """Raised when prompt settings input or persisted state is invalid."""


class GhostPromptSettings:
    """Read and atomically update one authenticated owner's prompt settings."""

    def __init__(
        self,
        settings_root: str | Path = DEFAULT_PROMPT_SETTINGS_ROOT,
    ) -> None:
        self.settings_root = Path(settings_root)

    def show(self, owner_sub: str) -> dict[str, Any]:
        """Return a validated snapshot, creating defaults lazily when absent."""
        owner = self._validate_owner_sub(owner_sub)
        with self._owner_lock(owner):
            return copy.deepcopy(self._read_or_create_unlocked(owner))

    def set(
        self,
        owner_sub: str,
        updates: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Apply validated persistent updates for one owner."""
        owner = self._validate_owner_sub(owner_sub)
        clean_updates = self._validate_updates(updates)
        with self._owner_lock(owner):
            settings = self._read_or_create_unlocked(owner)
            settings.update(clean_updates)
            self._write_unlocked(owner, settings)
            return copy.deepcopy(settings)

    def reset(self, owner_sub: str) -> dict[str, Any]:
        """Restore all persistent settings to their approved defaults."""
        owner = self._validate_owner_sub(owner_sub)
        settings = copy.deepcopy(DEFAULT_PROMPT_SETTINGS)
        with self._owner_lock(owner):
            self._write_unlocked(owner, settings)
        return copy.deepcopy(settings)

    def all_off(self, owner_sub: str) -> dict[str, Any]:
        """Disable all enrichment flags while preserving paths and recency."""
        owner = self._validate_owner_sub(owner_sub)
        with self._owner_lock(owner):
            settings = self._read_or_create_unlocked(owner)
            for key in ENRICHMENT_FLAG_KEYS:
                settings[key] = False
            self._write_unlocked(owner, settings)
            return copy.deepcopy(settings)

    def effective(
        self,
        owner_sub: str,
        overrides: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return a request-local settings snapshot with optional overrides."""
        settings = self.show(owner_sub)
        if overrides is not None:
            settings.update(self._validate_updates(overrides))
        return settings

    def settings_path(self, owner_sub: str) -> Path:
        """Return the deterministic owner-scoped JSON path."""
        owner = self._validate_owner_sub(owner_sub)
        return self.settings_root / owner / "prompt_settings.json"

    @staticmethod
    def _validate_owner_sub(owner_sub: str) -> str:
        owner = str(owner_sub or "").strip()
        if (
            owner in {"", ".", ".."}
            or _SAFE_PATH_PART.fullmatch(owner) is None
        ):
            raise PromptSettingsError(
                "owner_sub must contain only letters, numbers, '.', '_' or '-'"
            )
        return owner

    @staticmethod
    def _validate_updates(
        updates: Mapping[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(updates, Mapping):
            raise PromptSettingsError("settings updates must be an object")

        unsupported = set(updates).difference(SUPPORTED_SETTING_KEYS)
        if unsupported:
            raise PromptSettingsError(
                "unsupported prompt setting: " + ", ".join(sorted(unsupported))
            )

        clean: dict[str, Any] = {}
        for key, value in updates.items():
            if key in BOOLEAN_SETTING_KEYS:
                if not isinstance(value, bool):
                    raise PromptSettingsError(f"{key} must be boolean")
                clean[key] = value
                continue

            if value is None:
                clean[key] = None
            elif isinstance(value, str) and value.strip():
                clean[key] = value.strip()
            else:
                raise PromptSettingsError(
                    f"{key} must be null or a non-empty string"
                )

        return clean

    @contextmanager
    def _owner_lock(self, owner: str) -> Iterator[None]:
        owner_root = self.settings_root / owner
        owner_root.mkdir(parents=True, exist_ok=True)
        lock_path = owner_root / ".prompt_settings.lock"
        lock_file: TextIO = lock_path.open("a+", encoding="utf-8")
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            lock_file.close()

    def _read_or_create_unlocked(self, owner: str) -> dict[str, Any]:
        path = self.settings_root / owner / "prompt_settings.json"
        if not path.exists():
            settings = copy.deepcopy(DEFAULT_PROMPT_SETTINGS)
            self._write_unlocked(owner, settings)
            return settings

        try:
            with path.open("r", encoding="utf-8") as file:
                raw = json.load(file)
        except (OSError, json.JSONDecodeError) as error:
            raise PromptSettingsError("prompt settings JSON is unreadable") from error

        if not isinstance(raw, Mapping):
            raise PromptSettingsError("prompt settings JSON must contain an object")

        unsupported = set(raw).difference(SUPPORTED_SETTING_KEYS)
        if unsupported:
            raise PromptSettingsError(
                "prompt settings JSON contains unsupported keys"
            )

        merged = copy.deepcopy(DEFAULT_PROMPT_SETTINGS)
        merged.update(self._validate_updates(raw))
        return merged

    def _write_unlocked(
        self,
        owner: str,
        settings: Mapping[str, Any],
    ) -> None:
        clean_settings = copy.deepcopy(DEFAULT_PROMPT_SETTINGS)
        clean_settings.update(self._validate_updates(settings))

        owner_root = self.settings_root / owner
        owner_root.mkdir(parents=True, exist_ok=True)
        target = owner_root / "prompt_settings.json"

        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=owner_root,
                prefix=".prompt_settings.",
                suffix=".tmp",
                delete=False,
            ) as temp_file:
                temp_path = Path(temp_file.name)
                json.dump(
                    clean_settings,
                    temp_file,
                    ensure_ascii=False,
                    indent=2,
                )
                temp_file.write("\n")
                temp_file.flush()
                os.fsync(temp_file.fileno())

            os.replace(temp_path, target)
        finally:
            if temp_path is not None and temp_path.exists():
                temp_path.unlink()



TOOL_NAME = "ghost_prompt_settings"
TOOL_TITLE = "GHOST Prompt Settings"

_INSTRUCTIONS = load_memory_tool_instructions(
    "custom_prompt_settings.json"
)
TOOL_DESCRIPTION = _INSTRUCTIONS.tool_description
SERVER_INSTRUCTIONS = _INSTRUCTIONS.server_instruction

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": ["show", "set", "reset", "all_off"],
            "description": _INSTRUCTIONS.field_descriptions["action"],
        },
        "updates": {
            "type": "object",
            "properties": {
                **{
                    key: {"type": "boolean"}
                    for key in BOOLEAN_SETTING_KEYS
                },
                **{
                    key: {"type": ["string", "null"]}
                    for key in PATH_SETTING_KEYS
                },
            },
            "additionalProperties": False,
            "description": _INSTRUCTIONS.field_descriptions["updates"],
        },
    },
    "required": ["action"],
    "additionalProperties": False,
}

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": ["show", "set", "reset", "all_off"],
        },
        "settings": {
            "type": "object",
            "properties": {
                **{
                    key: {"type": "boolean"}
                    for key in BOOLEAN_SETTING_KEYS
                },
                **{
                    key: {"type": ["string", "null"]}
                    for key in PATH_SETTING_KEYS
                },
            },
            "required": list(SUPPORTED_SETTING_KEYS),
            "additionalProperties": False,
        },
    },
    "required": ["action", "settings"],
    "additionalProperties": False,
}


class GhostPromptSettingsTool:
    """Thin MCP adapter over owner-scoped prompt settings."""

    def __init__(self, settings: GhostPromptSettings) -> None:
        self._settings = settings

    def call_sanitized(
        self,
        owner_sub: str,
        arguments: Mapping[str, Any] | None,
    ) -> GhostToolResult:
        try:
            action, updates = self._validate_arguments(arguments)
            if action == "show":
                values = self._settings.show(owner_sub)
            elif action == "set":
                assert updates is not None
                values = self._settings.set(owner_sub, updates)
            elif action == "reset":
                values = self._settings.reset(owner_sub)
            else:
                values = self._settings.all_off(owner_sub)

            return GhostToolResult(
                content=[
                    {
                        "type": "text",
                        "text": f"GHOST prompt settings action '{action}' completed.",
                    }
                ],
                structuredContent={
                    "action": action,
                    "settings": values,
                },
            )
        except (PromptSettingsError, ValueError) as error:
            return GhostToolResult(
                content=[
                    {
                        "type": "text",
                        "text": (
                            "GHOST Prompt Settings failed. "
                            f"Reason: {error}."
                        ),
                    }
                ],
                structuredContent={},
                isError=True,
            )
        except Exception:
            return GhostToolResult(
                content=[
                    {
                        "type": "text",
                        "text": "GHOST Prompt Settings failed.",
                    }
                ],
                structuredContent={},
                isError=True,
            )

    @staticmethod
    def _validate_arguments(
        arguments: Mapping[str, Any] | None,
    ) -> tuple[str, Mapping[str, Any] | None]:
        if not isinstance(arguments, Mapping):
            raise ValueError("settings input is required")
        if set(arguments).difference({"action", "updates"}):
            raise ValueError("unsupported input property")

        action = arguments.get("action")
        if action not in {"show", "set", "reset", "all_off"}:
            raise ValueError("unsupported settings action")

        updates = arguments.get("updates")
        if action == "set":
            if not isinstance(updates, Mapping) or not updates:
                raise ValueError(
                    "action set requires a non-empty updates object"
                )
            return action, updates

        if "updates" in arguments:
            raise ValueError("updates is allowed only for action set")
        return action, None


def tool_metadata(
    required_scope: str | None = None,
) -> dict[str, Any]:
    """Build the OAuth-protected Prompt Settings descriptor."""
    scope = (
        required_scope
        if required_scope is not None
        else DEFAULT_REQUIRED_SCOPE
    ).strip()
    if not scope:
        raise ValueError("required_scope must not be empty")

    security_schemes = [{"type": "oauth2", "scopes": [scope]}]
    return {
        "name": TOOL_NAME,
        "title": TOOL_TITLE,
        "description": TOOL_DESCRIPTION,
        "inputSchema": INPUT_SCHEMA,
        "outputSchema": OUTPUT_SCHEMA,
        "securitySchemes": security_schemes,
        "_meta": {"securitySchemes": security_schemes.copy()},
        "annotations": {
            "destructiveHint": False,
            "readOnlyHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    }
