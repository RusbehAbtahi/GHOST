"""Verify Business-facing MCP input schemas stay explicit and composition-free."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

import pytest

from ragstream.mcp.ghost_cli import run_tool_metadata
from ragstream.mcp.ghost_memory_delete import tool_metadata as delete_tool_metadata
from ragstream.mcp.ghost_memory_recall import tool_metadata as recall_tool_metadata
from ragstream.mcp.ghost_memory_tag import tool_metadata as tag_tool_metadata
from ragstream.mcp.ghost_prompt_run import tool_metadata as prompt_run_tool_metadata
from ragstream.mcp.ghost_prompt_show import tool_metadata as prompt_show_tool_metadata
from ragstream.mcp.mcp_skill_loader import tool_metadata as skill_loader_tool_metadata


_COMPOSITION_KEYS = {"oneOf", "anyOf", "allOf", "not", "if", "then", "else"}


def _assert_no_schema_composition(value: Any) -> None:
    if isinstance(value, Mapping):
        assert _COMPOSITION_KEYS.isdisjoint(value)
        for child in value.values():
            _assert_no_schema_composition(child)
    elif isinstance(value, list):
        for child in value:
            _assert_no_schema_composition(child)


@pytest.mark.parametrize(
    ("name", "metadata_factory", "expected_fields"),
    [
        (
            "ghost_memory_tag",
            tag_tool_metadata,
            {"memory_type", "recall_key", "input_text", "output_text"},
        ),
        (
            "ghost_memory_recall",
            recall_tool_metadata,
            {"memory_type", "recall_key", "record_id", "query_description"},
        ),
        (
            "ghost_memory_delete",
            delete_tool_metadata,
            {"recall_key", "record_id", "collection_id", "delete_all_matches"},
        ),
        (
            "ghost_cli_run",
            run_tool_metadata,
            {"command", "confirmation_id", "confirmation_token"},
        ),
        (
            "ghost_skill_loader",
            skill_loader_tool_metadata,
            {"skill_domain", "query", "skill_ids"},
        ),
        (
            "ghost_prompt_show",
            prompt_show_tool_metadata,
            {"prompt_text", "prompt", "build_id", "general_skill_ids"},
        ),
        (
            "ghost_prompt_run",
            prompt_run_tool_metadata,
            {"prompt_text", "prompt", "build_id", "general_skill_ids"},
        ),
    ],
)
def test_business_facing_input_schema_is_explicit_and_flat(
    name: str,
    metadata_factory: Callable[[], dict[str, Any]],
    expected_fields: set[str],
) -> None:
    metadata = metadata_factory()
    schema = metadata["inputSchema"]

    assert metadata["name"] == name
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert expected_fields.issubset(schema["properties"])
    _assert_no_schema_composition(schema)
