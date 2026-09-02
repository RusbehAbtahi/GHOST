"""Live local MCP smoke client for the GHOST server.

This script connects through the real Streamable HTTP network path:

    ClientSession
    -> http://127.0.0.1:8000/mcp
    -> Uvicorn
    -> Starlette
    -> GhostMcpRuntime
    -> ghost_prompt_show

The GHOST MCP server must already be running in a separate terminal.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence
from typing import Final

import mcp.types as types
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


DEFAULT_SERVER_URL: Final[str] = "http://127.0.0.1:8000/mcp"
DEFAULT_PROMPT: Final[str] = "Explain the GHOST MCP server architecture."
EXPECTED_TOOL_NAME: Final[str] = "ghost_prompt_show"
EXPECTED_MODE: Final[str] = "show_prompt"


class SmokeTestError(RuntimeError):
    """Raised when the live MCP response violates the expected contract."""


def _parse_arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Call the live local GHOST MCP server through Streamable HTTP."
    )
    parser.add_argument(
        "--url",
        default=DEFAULT_SERVER_URL,
        help=f"MCP endpoint URL (default: {DEFAULT_SERVER_URL})",
    )
    parser.add_argument(
        "--prompt",
        default=DEFAULT_PROMPT,
        help="Prompt text sent to ghost_prompt_show.",
    )
    return parser.parse_args(argv)


def _extract_single_text(result: types.CallToolResult) -> str:
    if len(result.content) != 1:
        raise SmokeTestError(
            f"Expected exactly one content item, received {len(result.content)}."
        )

    content_item = result.content[0]
    if not isinstance(content_item, types.TextContent):
        raise SmokeTestError(
            "Expected the tool result to contain one TextContent item."
        )

    if not content_item.text.strip():
        raise SmokeTestError("The engineered prompt is empty.")

    return content_item.text


def _validate_tool_inventory(tools: list[types.Tool]) -> types.Tool:
    tool_names = [tool.name for tool in tools]

    if tool_names != [EXPECTED_TOOL_NAME]:
        raise SmokeTestError(
            "Unexpected MCP tool inventory: "
            f"expected [{EXPECTED_TOOL_NAME!r}], received {tool_names!r}."
        )

    return tools[0]


def _validate_call_result(result: types.CallToolResult) -> str:
    text = _extract_single_text(result)

    if result.isError:
        raise SmokeTestError(f"GHOST returned a tool error: {text}")

    structured = result.structuredContent
    if not isinstance(structured, dict):
        raise SmokeTestError("The tool result has no structuredContent object.")

    expected_keys = {"status", "mode", "prompt", "clarification_question", "general_skill_candidates", "receipt"}
    if set(structured) != expected_keys:
        raise SmokeTestError(
            "Unexpected structuredContent keys: "
            f"expected {sorted(expected_keys)!r}, received {sorted(structured)!r}."
        )

    engineered_prompt = structured.get("prompt")
    mode = structured.get("mode")

    if engineered_prompt != text:
        raise SmokeTestError(
            "Text content and structured engineered_prompt are not identical."
        )

    if mode != EXPECTED_MODE:
        raise SmokeTestError(
            f"Expected mode {EXPECTED_MODE!r}, received {mode!r}."
        )

    return text


async def run_live_smoke_test(*, url: str, prompt: str) -> None:
    clean_url = url.strip()
    clean_prompt = prompt.strip()

    if not clean_url:
        raise ValueError("The MCP endpoint URL must not be empty.")

    if not clean_prompt:
        raise ValueError("The prompt must not be empty.")

    print(f"Connecting to: {clean_url}")

    async with streamable_http_client(clean_url) as (
        read_stream,
        write_stream,
        _get_session_id,
    ):
        async with ClientSession(read_stream, write_stream) as session:
            initialization = await session.initialize()
            print(
                "Connected to MCP server: "
                f"{initialization.serverInfo.name} "
                f"{initialization.serverInfo.version}"
            )

            tools_result = await session.list_tools()
            tool = _validate_tool_inventory(tools_result.tools)
            print(f"Tool discovered: {tool.name}")

            call_result = await session.call_tool(
                EXPECTED_TOOL_NAME,
                arguments={"prompt_text": clean_prompt},
            )
            engineered_prompt = _validate_call_result(call_result)

            print("\nLive MCP smoke test PASSED")
            print("\nEngineered prompt returned by GHOST:\n")
            print(engineered_prompt)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_arguments(argv)

    try:
        asyncio.run(
            run_live_smoke_test(
                url=args.url,
                prompt=args.prompt,
            )
        )
    except KeyboardInterrupt:
        print("\nLive MCP smoke test cancelled.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(
            f"\nLive MCP smoke test FAILED: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
