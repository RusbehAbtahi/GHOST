"""Load and validate external client instructions for MCP memory tools.

This module keeps model-facing prompt text outside Python while preserving a
small typed boundary for tool modules. It does not define tool behavior,
schemas, persistence rules, or backend decisions.

Main classes:
    MemoryToolInstructions:
        Immutable instruction text consumed by one MCP memory tool.

Main functions:
    load_memory_tool_instructions():
        Loads one approved JSON file and validates its required structure.
"""

from __future__ import annotations

import json

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any


INSTRUCTIONS_DIRECTORY = Path(__file__).with_name("instructions")


@dataclass(frozen=True)
class MemoryToolInstructions:
    """Contain validated model-facing instructions for one memory tool."""

    tool_description: str
    server_instruction: str
    field_descriptions: dict[str, str]


@lru_cache(maxsize=8)
def load_memory_tool_instructions(
    filename: str,
) -> MemoryToolInstructions:
    """Load one local JSON instruction file by its safe basename."""
    if not isinstance(filename, str) or not filename.strip():
        raise ValueError("instruction filename must not be empty")

    clean_filename = filename.strip()
    if Path(clean_filename).name != clean_filename:
        raise ValueError("instruction filename must be a basename")
    if not clean_filename.endswith(".json"):
        raise ValueError("instruction filename must use the .json extension")

    instruction_path = INSTRUCTIONS_DIRECTORY / clean_filename
    try:
        raw_data = json.loads(instruction_path.read_text(encoding="utf-8"))
    except OSError as error:
        raise RuntimeError(
            f"memory instruction file could not be read: {clean_filename}"
        ) from error
    except json.JSONDecodeError as error:
        raise RuntimeError(
            f"memory instruction file is invalid JSON: {clean_filename}"
        ) from error

    if not isinstance(raw_data, dict):
        raise RuntimeError("memory instruction root must be an object")

    tool_description = _join_paragraphs(
        raw_data.get("tool_description"),
        "tool_description",
    )
    server_instruction = _join_paragraphs(
        raw_data.get("server_instruction"),
        "server_instruction",
    )
    field_descriptions = _validate_field_descriptions(
        raw_data.get("field_descriptions")
    )

    return MemoryToolInstructions(
        tool_description=tool_description,
        server_instruction=server_instruction,
        field_descriptions=field_descriptions,
    )


def _join_paragraphs(value: Any, field_name: str) -> str:
    if not isinstance(value, list) or not value:
        raise RuntimeError(f"{field_name} must be a non-empty string array")

    paragraphs: list[str] = []
    for paragraph in value:
        if not isinstance(paragraph, str) or not paragraph.strip():
            raise RuntimeError(
                f"{field_name} must contain only non-empty strings"
            )
        paragraphs.append(paragraph.strip())

    return " ".join(paragraphs)


def _validate_field_descriptions(value: Any) -> dict[str, str]:
    if not isinstance(value, dict) or not value:
        raise RuntimeError("field_descriptions must be a non-empty object")

    descriptions: dict[str, str] = {}
    for field_name, description in value.items():
        if not isinstance(field_name, str) or not field_name.strip():
            raise RuntimeError(
                "field_descriptions contains an invalid field name"
            )
        if not isinstance(description, str) or not description.strip():
            raise RuntimeError(
                f"field description must not be empty: {field_name}"
            )
        descriptions[field_name.strip()] = description.strip()

    return descriptions