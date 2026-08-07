"""Own and dispatch the GHOST MCP application tools.

This module is the application boundary behind the MCP runtime. It creates the
five approved GHOST tools, advertises their MCP metadata, dispatches tool calls,
and converts internal GHOST results into MCP CallToolResult objects. HTTP,
authentication, transport, and Uvicorn lifecycle stay in server.py.

Main classes:
    GhostMcpApplication:
        Owns the five GHOST tools and dispatches authenticated tool calls.

Main methods:
    list_tools():
        Returns the five OAuth-protected MCP tool definitions.
    call_tool():
        Executes one named GHOST tool and converts its result to MCP.

Important notes:
    Prompt engineering keeps its strict internal-result validation. Memory tools
    share one McpMemoryStore so Tag, Recall, List, and Delete see the same state.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict
from typing import Any

import mcp.types as types
from mcp.shared.exceptions import McpError

from ragstream.mcp.ghost_engineer_prompt import (
    ANSWER_PROMPT_MODE,
    ANSWER_PROMPT_WITH_MEMORY_MODE,
    SHOW_PROMPT_ONLY_MODE,
    SERVER_INSTRUCTIONS as PROMPT_SERVER_INSTRUCTIONS,
    GhostEngineerPromptTool,
    GhostToolResult,
    TOOL_NAME as PROMPT_TOOL_NAME,
    tool_metadata as prompt_tool_metadata,
)
from ragstream.mcp.ghost_memory_delete import (
    GhostMemoryDeleteTool,
    TOOL_NAME as MEMORY_DELETE_TOOL_NAME,
    tool_metadata as memory_delete_tool_metadata,
)
from ragstream.mcp.ghost_memory_list import (
    GhostMemoryListTool,
    TOOL_NAME as MEMORY_LIST_TOOL_NAME,
    tool_metadata as memory_list_tool_metadata,
)
from ragstream.mcp.ghost_memory_recall import (
    GhostMemoryRecallTool,
    TOOL_NAME as MEMORY_RECALL_TOOL_NAME,
    tool_metadata as memory_recall_tool_metadata,
)
from ragstream.mcp.ghost_memory_tag import (
    GhostMemoryTagTool,
    TOOL_NAME as MEMORY_TAG_TOOL_NAME,
    tool_metadata as memory_tag_tool_metadata,
)
from ragstream.mcp.prompt_engineering_runner import PromptEngineeringRunner
from ragstream.memory.mcp_memory_store import McpMemoryStore
from ragstream.textforge.RagLog import LogNoGUI


SERVER_INSTRUCTIONS = (
    "After every ghost_memory_tag call, report its receipt. Claim success only "
    "when saved is true, and include the returned episode title, recall key, "
    "and record ID. If the call fails, state that the memory was not saved and "
    "give its returned sanitized reason. "
    + PROMPT_SERVER_INSTRUCTIONS
)

GHOST_TOOL_NAMES = frozenset(
    {
        PROMPT_TOOL_NAME,
        MEMORY_TAG_TOOL_NAME,
        MEMORY_RECALL_TOOL_NAME,
        MEMORY_LIST_TOOL_NAME,
        MEMORY_DELETE_TOOL_NAME,
    }
)


class GhostMcpApplication:
    """Own the five GHOST tools and convert their results to MCP."""

    def __init__(
        self,
        tool: GhostEngineerPromptTool | None = None,
        required_scope: str | None = None,
        memory_store: McpMemoryStore | None = None,
    ) -> None:
        """Create production tools or accept injected test dependencies."""
        if tool is None:
            tool = GhostEngineerPromptTool(PromptEngineeringRunner())
        if memory_store is None:
            memory_store = McpMemoryStore()

        self.tool = tool
        self.memory_tag_tool = GhostMemoryTagTool(memory_store)
        self.memory_recall_tool = GhostMemoryRecallTool(memory_store)
        self.memory_list_tool = GhostMemoryListTool(memory_store)
        self.memory_delete_tool = GhostMemoryDeleteTool(memory_store)
        self.required_scope = required_scope

    def list_tools(self) -> list[types.Tool]:
        """Return the five OAuth-protected tools advertised to MCP clients."""
        prompt = prompt_tool_metadata(self.required_scope)
        prompt["annotations"]["openWorldHint"] = True

        definitions = (
            prompt,
            memory_tag_tool_metadata(self.required_scope),
            memory_recall_tool_metadata(self.required_scope),
            memory_list_tool_metadata(self.required_scope),
            memory_delete_tool_metadata(self.required_scope),
        )
        return [types.Tool.model_validate(item) for item in definitions]

    def call_tool(
        self,
        name: str,
        arguments: Mapping[str, Any] | None,
        owner_sub: str | None = None,
    ) -> types.CallToolResult:
        """Execute the requested tool and return a complete MCP result."""
        if name == PROMPT_TOOL_NAME:
            return self._to_mcp_result(self.tool.call_sanitized(arguments))

        if name == MEMORY_TAG_TOOL_NAME:
            result = self.memory_tag_tool.call_sanitized(
                owner_sub or "",
                arguments,
            )
            return self._to_memory_mcp_result(result)

        if name == MEMORY_RECALL_TOOL_NAME:
            result = self.memory_recall_tool.call_sanitized(
                owner_sub or "",
                arguments,
            )
            return self._to_memory_mcp_result(result)

        if name == MEMORY_LIST_TOOL_NAME:
            result = self.memory_list_tool.call_sanitized(
                owner_sub or "",
                arguments,
            )
            return self._to_memory_mcp_result(result)

        if name == MEMORY_DELETE_TOOL_NAME:
            result = self.memory_delete_tool.call_sanitized(
                owner_sub or "",
                arguments,
            )
            return self._to_memory_mcp_result(result)

        raise McpError(
            types.ErrorData(
                code=types.INVALID_PARAMS,
                message=f"Unknown tool: {name}",
            )
        )

    @classmethod
    def _to_mcp_result(cls, result: GhostToolResult) -> types.CallToolResult:
        """Validate and convert one prompt-engineering result to MCP."""
        text = cls._single_text(result.content)
        if result.isError:
            return cls._error_result(text or "GHOST prompt engineering failed")

        structured_content = result.structuredContent
        engineered_prompt = structured_content.get("engineered_prompt")
        mode = structured_content.get("mode")

        valid_result = (
            text is not None
            and isinstance(engineered_prompt, str)
            and bool(engineered_prompt.strip())
            and text == engineered_prompt
            and structured_content.get("stage") == "a2"
            and mode in {
                SHOW_PROMPT_ONLY_MODE,
                ANSWER_PROMPT_MODE,
                ANSWER_PROMPT_WITH_MEMORY_MODE,
            }
            and set(structured_content) == {
                "engineered_prompt",
                "stage",
                "mode",
            }
        )

        if not valid_result:
            LogNoGUI(
                "GHOST MCP rejected an invalid internal tool result.",
                "ERROR",
                "INTERNAL",
            )
            return cls._error_result("GHOST returned an invalid tool result")

        return types.CallToolResult(
            content=[
                types.TextContent(
                    type="text",
                    text=engineered_prompt,
                )
            ],
            structuredContent={
                "engineered_prompt": engineered_prompt,
                "stage": "a2",
                "mode": mode,
            },
            isError=False,
        )

    @staticmethod
    def _to_memory_mcp_result(
        result: GhostToolResult,
    ) -> types.CallToolResult:
        """Convert one sanitized memory-tool result to the MCP result model."""
        return types.CallToolResult.model_validate(asdict(result))

    @staticmethod
    def _single_text(content: object) -> str | None:
        """Return text only when content contains one exact text item."""
        if not isinstance(content, list) or len(content) != 1:
            return None

        item = content[0]
        if not isinstance(item, Mapping):
            return None

        text = item.get("text")
        valid_item = (
            set(item) == {"type", "text"}
            and item.get("type") == "text"
            and isinstance(text, str)
        )
        return text if valid_item else None

    @staticmethod
    def _error_result(message: str) -> types.CallToolResult:
        """Create one sanitized MCP tool-error response."""
        return types.CallToolResult(
            content=[
                types.TextContent(
                    type="text",
                    text=message,
                )
            ],
            isError=True,
        )