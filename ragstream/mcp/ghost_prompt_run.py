"""Expose the shared GHOST prompt builder as a build-and-run MCP tool."""

from __future__ import annotations

from typing import Any

from ragstream.mcp.ghost_prompt_builder import GhostPromptBuilder
from ragstream.mcp.ghost_prompt_show import (
    INPUT_SCHEMA,
    OUTPUT_SCHEMA,
    GhostPromptToolAdapter,
    _tool_metadata,
)
from ragstream.mcp.memory_tool_instructions import (
    load_memory_tool_instructions,
)


TOOL_NAME = "ghost_prompt_run"
TOOL_TITLE = "GHOST Prompt Run"
MODE_RUN = "run_prompt"

_INSTRUCTIONS = load_memory_tool_instructions("custom_prompt_run.json")
TOOL_DESCRIPTION = _INSTRUCTIONS.tool_description
SERVER_INSTRUCTIONS = _INSTRUCTIONS.server_instruction


class GhostPromptRunTool(GhostPromptToolAdapter):
    """Build one final prompt for exactly one client-side execution."""

    def __init__(self, builder: GhostPromptBuilder) -> None:
        super().__init__(
            builder,
            mode=MODE_RUN,
            failure_label="GHOST Prompt Run failed.",
        )


def tool_metadata(
    required_scope: str | None = None,
) -> dict[str, Any]:
    """Build the OAuth-protected Prompt Run descriptor."""
    return _tool_metadata(
        name=TOOL_NAME,
        title=TOOL_TITLE,
        description=TOOL_DESCRIPTION,
        required_scope=required_scope,
    )
