"""Shared neutral contracts used by GHOST MCP tool adapters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


DEFAULT_REQUIRED_SCOPE = "https://ghost.rusbehabtahi.com/mcp/invoke"


@dataclass(frozen=True)
class GhostToolResult:
    """Internal result transferred from a GHOST tool to the MCP application."""

    content: list[dict[str, Any]]
    structuredContent: dict[str, Any]
    isError: bool = False
