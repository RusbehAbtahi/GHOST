"""Verify MCP Skill tag schemas stay catalog-driven rather than hard-coded."""

from __future__ import annotations

from ragstream.mcp.mcp_skill_loader import (
    INPUT_SCHEMA as LOADER_INPUT_SCHEMA,
    OUTPUT_SCHEMA as LOADER_OUTPUT_SCHEMA,
)
from ragstream.mcp.mcp_skill_maker import (
    INPUT_SCHEMA as MAKER_INPUT_SCHEMA,
    OUTPUT_SCHEMA as MAKER_OUTPUT_SCHEMA,
)


def _tag_items(schema: dict, property_name: str) -> dict:
    return schema["properties"][property_name]["items"]


def test_loader_tag_schemas_accept_runtime_catalog_strings() -> None:
    input_properties = LOADER_INPUT_SCHEMA["properties"]
    output_properties = LOADER_OUTPUT_SCHEMA["properties"]

    for schema, property_name in (
        (LOADER_INPUT_SCHEMA, "include_tags"),
        (LOADER_INPUT_SCHEMA, "exclude_tags"),
        (LOADER_OUTPUT_SCHEMA, "include_tags"),
        (LOADER_OUTPUT_SCHEMA, "exclude_tags"),
    ):
        items = _tag_items(schema, property_name)
        assert items["type"] == "string"
        assert "enum" not in items

    assert "include_tags" in input_properties
    assert "exclude_tags" in input_properties
    assert "include_tags" in output_properties
    assert "exclude_tags" in output_properties
    assert "include_tags" not in output_properties["candidates"]
    assert "exclude_tags" not in output_properties["candidates"]


def test_maker_skill_tag_schema_is_not_a_fixed_vocabulary() -> None:
    for schema in (MAKER_INPUT_SCHEMA, MAKER_OUTPUT_SCHEMA):
        items = _tag_items(schema, "skill_tags")
        assert items["type"] == "string"
        assert "enum" not in items

    assert "skill_tags" not in MAKER_INPUT_SCHEMA["required"]
