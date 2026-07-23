"""External MCP tool contract for ghost_engineer_prompt."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from ragstream.mcp.prompt_engineering_runner import PromptEngineeringError, PromptEngineeringRunner

TOOL_NAME = "ghost_engineer_prompt"
TOOL_TITLE = "GHOST Prompt Engineering"
TOOL_DESCRIPTION = (
    "Accepts a user prompt, runs GHOST PreProcessing and A2 PromptShaper, "
    "returns the engineered prompt, does not answer the original prompt, and is "
    "intended to present the engineered prompt back to the user."
)
INPUT_SCHEMA = {
    "type": "object",
    "properties": {"prompt_text": {"type": "string"}},
    "required": ["prompt_text"],
    "additionalProperties": False,
}
OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "engineered_prompt": {"type": "string", "minLength": 1},
        "stage": {"type": "string", "const": "a2"},
    },
    "required": ["engineered_prompt", "stage"],
    "additionalProperties": False,
}


class ToolInputError(ValueError):
    """The tool arguments do not satisfy the public MCP input contract."""


class ToolExecutionError(RuntimeError):
    """A sanitized tool-visible processing error."""


@dataclass(frozen=True)
class GhostToolResult:
    content: list[dict[str, str]]
    structuredContent: dict[str, str]
    isError: bool = False


def validate_arguments(arguments: Mapping[str, Any] | None) -> str:
    if not isinstance(arguments, Mapping):
        raise ToolInputError("prompt_text is required and must be a non-empty string")
    unsupported = set(arguments).difference({"prompt_text"})
    if unsupported:
        raise ToolInputError("unsupported input property")
    if "prompt_text" not in arguments:
        raise ToolInputError("prompt_text is required and must be a non-empty string")
    prompt_text = arguments["prompt_text"]
    if not isinstance(prompt_text, str):
        raise ToolInputError("prompt_text must be a non-empty string")
    if not prompt_text.strip():
        raise ToolInputError("prompt_text must be a non-empty string")
    return prompt_text


class GhostEngineerPromptTool:
    """Thin MCP adapter for the approved prompt-engineering use case."""

    def __init__(self, runner: PromptEngineeringRunner) -> None:
        self._runner = runner

    def call(self, arguments: Mapping[str, Any] | None) -> GhostToolResult:
        prompt_text = validate_arguments(arguments)
        try:
            engineered_prompt = self._runner.run(prompt_text)
        except PromptEngineeringError as exc:
            raise ToolExecutionError(str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            raise ToolExecutionError("GHOST prompt engineering failed") from exc
        return GhostToolResult(
            content=[{"type": "text", "text": engineered_prompt}],
            structuredContent={"engineered_prompt": engineered_prompt, "stage": "a2"},
        )

    def call_sanitized(self, arguments: Mapping[str, Any] | None) -> GhostToolResult:
        try:
            return self.call(arguments)
        except (ToolInputError, ToolExecutionError) as exc:
            return GhostToolResult(content=[{"type": "text", "text": str(exc)}], structuredContent={}, isError=True)


def tool_metadata() -> dict[str, Any]:
    return {
        "name": TOOL_NAME,
        "title": TOOL_TITLE,
        "description": TOOL_DESCRIPTION,
        "inputSchema": INPUT_SCHEMA,
        "outputSchema": OUTPUT_SCHEMA,
        "annotations": {"destructiveHint": False, "readOnlyHint": True, "idempotentHint": False},
    }
