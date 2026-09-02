"""Verify MCP Skill tag schemas match the runtime tag contract."""

from __future__ import annotations

from ragstream.mcp.mcp_skill_loader import (
    INPUT_SCHEMA as LOADER_INPUT_SCHEMA,
    OUTPUT_SCHEMA as LOADER_OUTPUT_SCHEMA,
)
from ragstream.mcp.mcp_skill_maker import (
    INPUT_SCHEMA as MAKER_INPUT_SCHEMA,
    OUTPUT_SCHEMA as MAKER_OUTPUT_SCHEMA,
)


EXPECTED_TAGS = {"STANDARD", "GHOST"}


def _tag_enum(schema: dict, property_name: str) -> set[str]:
    return set(
        schema["properties"][property_name]["items"]["enum"]
    )


def test_loader_tag_filters_are_top_level_schema_properties() -> None:
    input_properties = LOADER_INPUT_SCHEMA["properties"]
    output_properties = LOADER_OUTPUT_SCHEMA["properties"]

    assert _tag_enum(LOADER_INPUT_SCHEMA, "include_tags") == EXPECTED_TAGS
    assert _tag_enum(LOADER_INPUT_SCHEMA, "exclude_tags") == EXPECTED_TAGS
    assert _tag_enum(LOADER_OUTPUT_SCHEMA, "include_tags") == EXPECTED_TAGS
    assert _tag_enum(LOADER_OUTPUT_SCHEMA, "exclude_tags") == EXPECTED_TAGS
    assert "include_tags" in input_properties
    assert "exclude_tags" in input_properties
    assert "include_tags" in output_properties
    assert "exclude_tags" in output_properties
    assert "include_tags" not in output_properties["candidates"]
    assert "exclude_tags" not in output_properties["candidates"]


def test_maker_skill_tags_use_the_same_controlled_vocabulary() -> None:
    assert _tag_enum(MAKER_INPUT_SCHEMA, "skill_tags") == EXPECTED_TAGS
    assert _tag_enum(MAKER_OUTPUT_SCHEMA, "skill_tags") == EXPECTED_TAGS
    assert "skill_tags" not in MAKER_INPUT_SCHEMA["required"]
