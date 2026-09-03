"""Own and dispatch the GHOST MCP application tools.

This module is the application boundary behind the MCP runtime. It creates the
approved GHOST tools, advertises their MCP metadata, dispatches tool calls,
and converts internal GHOST results into MCP CallToolResult objects. HTTP,
authentication, transport, and Uvicorn lifecycle stay in server.py.

Main classes:
    GhostMcpApplication:
        Owns the GHOST tools and dispatches authenticated tool calls.

Main methods:
    list_tools():
        Returns the OAuth-protected MCP tool definitions.
    call_tool():
        Executes one named GHOST tool and converts its result to MCP.
    cleanup_expired_clipboard():
        Physically removes expired Clipboard histories during startup.

Important notes:
    Prompt engineering keeps its strict internal-result validation. Shared
    memory, Collection, and Clipboard tools use one storage root and SQLite
    index. Persistent Chat uses its dedicated MCP policy store. CLI execution
    delegates to the owner-scoped command service.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict
from typing import Any

import mcp.types as types
from mcp.shared.exceptions import McpError

from ragstream.cli.command_service import CommandService
from ragstream.mcp.ghost_cli import (
    ASYNC_TOOL_NAME as CLI_ASYNC_TOOL_NAME,
    CLI_SERVER_INSTRUCTIONS,
    RUN_TOOL_NAME as CLI_RUN_TOOL_NAME,
    GhostCliTool,
    async_tool_metadata as cli_async_tool_metadata,
    run_tool_metadata as cli_run_tool_metadata,
)
from ragstream.mcp.ghost_prompt_builder import GhostPromptBuilder
from ragstream.mcp.ghost_prompt_run import (
    SERVER_INSTRUCTIONS as PROMPT_RUN_SERVER_INSTRUCTIONS,
    GhostPromptRunTool,
    TOOL_NAME as PROMPT_RUN_TOOL_NAME,
    tool_metadata as prompt_run_tool_metadata,
)
from ragstream.mcp.ghost_prompt_settings import (
    SERVER_INSTRUCTIONS as PROMPT_SETTINGS_SERVER_INSTRUCTIONS,
    GhostPromptSettings,
    GhostPromptSettingsTool,
    TOOL_NAME as PROMPT_SETTINGS_TOOL_NAME,
    tool_metadata as prompt_settings_tool_metadata,
)
from ragstream.mcp.ghost_prompt_show import (
    SERVER_INSTRUCTIONS as PROMPT_SHOW_SERVER_INSTRUCTIONS,
    GhostPromptShowTool,
    TOOL_NAME as PROMPT_SHOW_TOOL_NAME,
    tool_metadata as prompt_show_tool_metadata,
)
from ragstream.mcp.mcp_tool_contracts import GhostToolResult
from ragstream.mcp.ghost_memory_collection_init import (
    SERVER_INSTRUCTIONS as COLLECTION_INIT_SERVER_INSTRUCTIONS,
    GhostMemoryCollectionInitTool,
    TOOL_NAME as COLLECTION_INIT_TOOL_NAME,
    tool_metadata as collection_init_tool_metadata,
)
from ragstream.mcp.ghost_memory_delete import (
    SERVER_INSTRUCTIONS as MEMORY_DELETE_SERVER_INSTRUCTIONS,
    GhostMemoryDeleteTool,
    TOOL_NAME as MEMORY_DELETE_TOOL_NAME,
    tool_metadata as memory_delete_tool_metadata,
)
from ragstream.mcp.ghost_memory_list import (
    SERVER_INSTRUCTIONS as MEMORY_LIST_SERVER_INSTRUCTIONS,
    GhostMemoryListTool,
    TOOL_NAME as MEMORY_LIST_TOOL_NAME,
    tool_metadata as memory_list_tool_metadata,
)
from ragstream.mcp.ghost_memory_recall import (
    SERVER_INSTRUCTIONS as MEMORY_RECALL_SERVER_INSTRUCTIONS,
    GhostMemoryRecallTool,
    TOOL_NAME as MEMORY_RECALL_TOOL_NAME,
    tool_metadata as memory_recall_tool_metadata,
)
from ragstream.mcp.ghost_memory_tag import (
    SERVER_INSTRUCTIONS as MEMORY_SAVE_SERVER_INSTRUCTIONS,
    GhostMemoryTagTool,
    TOOL_NAME as MEMORY_TAG_TOOL_NAME,
    tool_metadata as memory_tag_tool_metadata,
)
from ragstream.mcp.ghost_persistent_chat import (
    APPEND_TOOL_NAME as PERSISTENT_CHAT_APPEND_TOOL_NAME,
    INIT_TOOL_NAME as PERSISTENT_CHAT_INIT_TOOL_NAME,
    PERSISTENT_CHAT_SERVER_INSTRUCTIONS,
    RESUME_TOOL_NAME as PERSISTENT_CHAT_RESUME_TOOL_NAME,
    GhostPersistentChatTool,
    append_tool_metadata as persistent_chat_append_tool_metadata,
    init_tool_metadata as persistent_chat_init_tool_metadata,
    resume_tool_metadata as persistent_chat_resume_tool_metadata,
)
from ragstream.mcp.ghost_skill_tag_settings import (
    SERVER_INSTRUCTIONS as SKILL_TAG_SETTINGS_SERVER_INSTRUCTIONS,
    GhostSkillTagSettingsTool,
    TOOL_NAME as SKILL_TAG_SETTINGS_TOOL_NAME,
    tool_metadata as skill_tag_settings_tool_metadata,
)
from ragstream.mcp.mcp_skill_loader import (
    SERVER_INSTRUCTIONS as SKILL_LOADER_SERVER_INSTRUCTIONS,
    McpSkillLoaderTool,
    TOOL_NAME as SKILL_LOADER_TOOL_NAME,
    tool_metadata as skill_loader_tool_metadata,
)
from ragstream.mcp.mcp_skill_maker import (
    SERVER_INSTRUCTIONS as SKILL_MAKER_SERVER_INSTRUCTIONS,
    McpSkillMakerTool,
    TOOL_NAME as SKILL_MAKER_TOOL_NAME,
    tool_metadata as skill_maker_tool_metadata,
)
from ragstream.memory.mcp_clipboard_store import McpClipboardStore
from ragstream.memory.mcp_memory_collection_retriever import (
    McpMemoryCollectionRetriever,
)
from ragstream.memory.mcp_memory_collection_store import (
    McpMemoryCollectionStore,
)
from ragstream.memory.mcp_memory_store import McpMemoryStore
from ragstream.memory.mcp_persistent_chat_store import (
    McpPersistentChatStore,
)
from ragstream.skills.skill_tags import SkillTagCatalog


SERVER_INSTRUCTIONS = (
    COLLECTION_INIT_SERVER_INSTRUCTIONS
    + " "
    + MEMORY_SAVE_SERVER_INSTRUCTIONS
    + " "
    + MEMORY_RECALL_SERVER_INSTRUCTIONS
    + " "
    + MEMORY_LIST_SERVER_INSTRUCTIONS
    + " "
    + MEMORY_DELETE_SERVER_INSTRUCTIONS
    + " "
    + PERSISTENT_CHAT_SERVER_INSTRUCTIONS
    + " "
    + CLI_SERVER_INSTRUCTIONS
    + " "
    + SKILL_LOADER_SERVER_INSTRUCTIONS
    + " "
    + SKILL_MAKER_SERVER_INSTRUCTIONS
    + " "
    + SKILL_TAG_SETTINGS_SERVER_INSTRUCTIONS
    + " "
    + PROMPT_SHOW_SERVER_INSTRUCTIONS
    + " "
    + PROMPT_RUN_SERVER_INSTRUCTIONS
    + " "
    + PROMPT_SETTINGS_SERVER_INSTRUCTIONS
)

GHOST_TOOL_NAMES = frozenset(
    {
        PROMPT_SHOW_TOOL_NAME,
        PROMPT_RUN_TOOL_NAME,
        PROMPT_SETTINGS_TOOL_NAME,
        MEMORY_TAG_TOOL_NAME,
        COLLECTION_INIT_TOOL_NAME,
        MEMORY_RECALL_TOOL_NAME,
        MEMORY_LIST_TOOL_NAME,
        MEMORY_DELETE_TOOL_NAME,
        PERSISTENT_CHAT_INIT_TOOL_NAME,
        PERSISTENT_CHAT_APPEND_TOOL_NAME,
        PERSISTENT_CHAT_RESUME_TOOL_NAME,
        CLI_RUN_TOOL_NAME,
        CLI_ASYNC_TOOL_NAME,
        SKILL_LOADER_TOOL_NAME,
        SKILL_MAKER_TOOL_NAME,
        SKILL_TAG_SETTINGS_TOOL_NAME,
    }
)


class GhostMcpApplication:
    """Own the GHOST tools and convert their results to MCP."""

    def __init__(
        self,
        prompt_builder: GhostPromptBuilder | None = None,
        prompt_settings: GhostPromptSettings | None = None,
        skill_tag_catalog: SkillTagCatalog | None = None,
        required_scope: str | None = None,
        memory_store: McpMemoryStore | None = None,
        persistent_chat_store: McpPersistentChatStore | None = None,
        collection_store: McpMemoryCollectionStore | None = None,
        collection_retriever: (
            McpMemoryCollectionRetriever | None
        ) = None,
        clipboard_store: McpClipboardStore | None = None,
        cli_service: CommandService | None = None,
    ) -> None:
        """Create production tools or accept injected test dependencies."""
        if prompt_settings is None:
            prompt_settings = GhostPromptSettings()
        if skill_tag_catalog is None:
            skill_tag_catalog = SkillTagCatalog()
        if prompt_builder is None:
            prompt_builder = GhostPromptBuilder(
                settings=prompt_settings
            )

        if memory_store is None:
            memory_store = McpMemoryStore()

        if persistent_chat_store is None:
            persistent_chat_store = McpPersistentChatStore(
                memory_root=memory_store.memory_root,
                sqlite_path=memory_store.sqlite_path,
            )

        if collection_store is None:
            collection_store = McpMemoryCollectionStore(
                memory_root=memory_store.memory_root,
                sqlite_path=memory_store.sqlite_path,
            )

        if collection_retriever is None:
            collection_retriever = McpMemoryCollectionRetriever(
                memory_root=memory_store.memory_root,
                sqlite_path=memory_store.sqlite_path,
            )

        if clipboard_store is None:
            clipboard_store = McpClipboardStore(
                memory_root=memory_store.memory_root,
                sqlite_path=memory_store.sqlite_path,
            )

        self.prompt_show_tool = GhostPromptShowTool(prompt_builder)
        self.prompt_run_tool = GhostPromptRunTool(prompt_builder)
        self.prompt_settings_tool = GhostPromptSettingsTool(
            prompt_settings
        )
        self.clipboard_store = clipboard_store

        self.collection_init_tool = (
            GhostMemoryCollectionInitTool(
                collection_store
            )
        )

        self.memory_tag_tool = GhostMemoryTagTool(
            memory_store,
            collection_store,
            clipboard_store,
        )

        self.memory_recall_tool = GhostMemoryRecallTool(
            memory_store,
            collection_retriever,
            clipboard_store,
        )

        self.memory_list_tool = GhostMemoryListTool(
            memory_store,
            collection_retriever,
        )

        self.memory_delete_tool = GhostMemoryDeleteTool(
            memory_store,
            collection_store,
        )

        self.persistent_chat_tool = GhostPersistentChatTool(
            persistent_chat_store
        )

        self.cli_tool = GhostCliTool(
            cli_service or CommandService()
        )

        # Each Skill tool creates its own request-scoped SkillManager. The MCP
        # application owns only the stateless adapters.
        self.skill_tag_settings_tool = GhostSkillTagSettingsTool(
            skill_tag_catalog
        )
        self.skill_loader_tool = McpSkillLoaderTool(
            skill_tag_catalog=skill_tag_catalog
        )
        self.skill_maker_tool = McpSkillMakerTool(
            skill_tag_catalog=skill_tag_catalog
        )

        self.required_scope = required_scope

    def cleanup_expired_clipboard(self) -> dict[str, Any]:
        """Physically remove expired Clipboard histories."""
        return self.clipboard_store.cleanup_expired()

    def list_tools(self) -> list[types.Tool]:
        """Return the OAuth-protected tools advertised to MCP clients."""
        definitions = (
            prompt_show_tool_metadata(self.required_scope),
            prompt_run_tool_metadata(self.required_scope),
            prompt_settings_tool_metadata(self.required_scope),
            collection_init_tool_metadata(self.required_scope),
            memory_tag_tool_metadata(self.required_scope),
            memory_recall_tool_metadata(self.required_scope),
            memory_list_tool_metadata(self.required_scope),
            memory_delete_tool_metadata(self.required_scope),
            persistent_chat_init_tool_metadata(
                self.required_scope
            ),
            persistent_chat_append_tool_metadata(
                self.required_scope
            ),
            persistent_chat_resume_tool_metadata(
                self.required_scope
            ),
            cli_run_tool_metadata(self.required_scope),
            cli_async_tool_metadata(self.required_scope),
            skill_loader_tool_metadata(self.required_scope),
            skill_maker_tool_metadata(self.required_scope),
            skill_tag_settings_tool_metadata(self.required_scope),
        )

        return [
            types.Tool.model_validate(item)
            for item in definitions
        ]

    def call_tool(
        self,
        name: str,
        arguments: Mapping[str, Any] | None,
        owner_sub: str | None = None,
    ) -> types.CallToolResult:
        """Execute the requested tool and return a complete MCP result."""
        if name == PROMPT_SHOW_TOOL_NAME:
            result = self.prompt_show_tool.call_sanitized(
                owner_sub or "",
                arguments,
            )
            return self._to_memory_mcp_result(result)

        if name == PROMPT_RUN_TOOL_NAME:
            result = self.prompt_run_tool.call_sanitized(
                owner_sub or "",
                arguments,
            )
            return self._to_memory_mcp_result(result)

        if name == PROMPT_SETTINGS_TOOL_NAME:
            result = self.prompt_settings_tool.call_sanitized(
                owner_sub or "",
                arguments,
            )
            return self._to_memory_mcp_result(result)

        if name == MEMORY_TAG_TOOL_NAME:
            result = self.memory_tag_tool.call_sanitized(
                owner_sub or "",
                arguments,
            )
            return self._to_memory_mcp_result(result)

        if name == COLLECTION_INIT_TOOL_NAME:
            result = self.collection_init_tool.call_sanitized(
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

        if name == PERSISTENT_CHAT_INIT_TOOL_NAME:
            result = self.persistent_chat_tool.init_sanitized(
                owner_sub or "",
                arguments,
            )
            return self._to_memory_mcp_result(result)

        if name == PERSISTENT_CHAT_APPEND_TOOL_NAME:
            result = self.persistent_chat_tool.append_sanitized(
                owner_sub or "",
                arguments,
            )
            return self._to_memory_mcp_result(result)

        if name == PERSISTENT_CHAT_RESUME_TOOL_NAME:
            result = self.persistent_chat_tool.resume_sanitized(
                owner_sub or "",
                arguments,
            )
            return self._to_memory_mcp_result(result)

        if name == CLI_RUN_TOOL_NAME:
            result = self.cli_tool.run_sanitized(
                owner_sub or "",
                arguments,
            )
            return self._to_memory_mcp_result(result)

        if name == CLI_ASYNC_TOOL_NAME:
            result = self.cli_tool.async_sanitized(
                owner_sub or "",
                arguments,
            )
            return self._to_memory_mcp_result(result)

        if name == SKILL_TAG_SETTINGS_TOOL_NAME:
            result = self.skill_tag_settings_tool.call_sanitized(
                owner_sub or "",
                arguments,
            )
            return self._to_memory_mcp_result(result)

        if name == SKILL_LOADER_TOOL_NAME:
            result = self.skill_loader_tool.call_sanitized(
                owner_sub or "",
                arguments,
            )
            return self._to_memory_mcp_result(result)

        if name == SKILL_MAKER_TOOL_NAME:
            result = self.skill_maker_tool.call_sanitized(
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

    @staticmethod
    def _to_memory_mcp_result(
        result: GhostToolResult,
    ) -> types.CallToolResult:
        """Convert one sanitized memory result to the MCP model."""
        return types.CallToolResult.model_validate(
            asdict(result)
        )
