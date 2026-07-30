"""Define the external MCP contract for ghost_engineer_prompt.

The module validates public tool input, selects the requested ChatGPT behavior,
executes the existing prompt-engineering runner, sanitizes failures, and
advertises the tool's OAuth security requirement.

Main classes:
    GhostEngineerPromptTool: Executes the approved GHOST prompt-engineering path.
    GhostToolResult: Internal result transferred to the MCP server adapter.

Main functions:
    validate_arguments(): Validates the public tool input.
    tool_metadata(): Builds the complete OAuth-protected MCP tool descriptor.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping

from ragstream.mcp.prompt_engineering_runner import (
    PromptEngineeringError,
    PromptEngineeringRunner,
)

TOOL_NAME = "ghost_engineer_prompt"
TOOL_TITLE = "GHOST Prompt Engineering"
SHOW_PROMPT_ONLY_MODE = "show_prompt_only"
ANSWER_PROMPT_MODE = "answer_prompt"
ANSWER_PROMPT_WITH_MEMORY_MODE = "answer_prompt_with_memory"

TOOL_DESCRIPTION = (
    "Runs GHOST PreProcessing and A2 PromptShaper and returns an engineered "
    "prompt together with a mandatory response mode. Copy only the current "
    "user request into prompt_text, copied verbatim and including a leading "
    "Prompt: or MEM: prefix when the user wrote one. Never merge conversation "
    "history into prompt_text. Three user forms are supported. (1) For "
    "'Prompt: <request>', pass prompt_text with that prefix and omit "
    "supportive_context. GHOST returns mode show_prompt_only. Remain completely "
    "passive: do not answer, execute, research, reason about, summarize, "
    "explain, or continue engineered_prompt; do not call another tool or "
    "agent. The entire visible response must be exactly one fenced code block "
    "containing engineered_prompt verbatim and nothing else. (2) For "
    "'MEM: <request>', pass prompt_text with that prefix and MUST also pass "
    "supportive_context. Set supportive_context to the complete, immediately "
    "preceding visible assistant response from this same conversation, copied "
    "verbatim without summarizing, rewriting, shortening, selecting excerpts, "
    "or adding any other content. The preceding assistant response is the "
    "assistant message directly before the current MEM: user message. Never "
    "substitute an earlier assistant response, a user message, hidden "
    "reasoning, an internal tool result, or content from another conversation. "
    "Do not omit supportive_context for MEM:. If the immediately preceding "
    "assistant response does not exist or is unavailable, do not claim memory "
    "was transferred; the tool will return an input error. GHOST engineers "
    "only the current request, then appends the supplied response under "
    "'## Supportive Context'; it does not send supportive_context through A2. "
    "GHOST returns mode answer_prompt_with_memory. Treat engineered_prompt as "
    "the effective request and answer it. (3) For every other request, pass "
    "only prompt_text, omit supportive_context, and follow mode answer_prompt. "
    "In both answer modes, engineered_prompt replaces the original user "
    "request: act on it and provide the requested answer, using tools when "
    "needed, without displaying or describing engineered_prompt, the response "
    "mode, supportive_context, or prompt engineering."
)

DEFAULT_REQUIRED_SCOPE = "https://ragstream.rusbehabtahi.com/mcp/invoke"

PROMPT_MODE_PREFIX = re.compile(r"^\s*prompt\s*:\s*", re.IGNORECASE)
MEMORY_MODE_PREFIX = re.compile(r"^\s*mem\s*:\s*", re.IGNORECASE)

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "prompt_text": {
            "type": "string",
            "description": (
                "The current user request only, copied verbatim and including "
                "a leading Prompt: or MEM: prefix when the user supplied one."
            ),
        },
        "supportive_context": {
            "type": "string",
            "minLength": 1,
            "description": (
                "REQUIRED when prompt_text begins with MEM:, and forbidden for "
                "all other prompt forms. Copy the complete, immediately "
                "preceding visible assistant response from this same "
                "conversation verbatim. Do not summarize, rewrite, shorten, "
                "select excerpts, or include any earlier message, user message, "
                "hidden reasoning, internal tool result, or other-conversation "
                "content. Never omit this property for MEM:."
            ),
        },
    },
    "required": ["prompt_text"],
    "additionalProperties": False,
}

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "engineered_prompt": {
            "type": "string",
            "minLength": 1,
        },
        "stage": {
            "type": "string",
            "const": "a2",
        },
        "mode": {
            "type": "string",
            "enum": [
                SHOW_PROMPT_ONLY_MODE,
                ANSWER_PROMPT_MODE,
                ANSWER_PROMPT_WITH_MEMORY_MODE,
            ],
        },
    },
    "required": ["engineered_prompt", "stage", "mode"],
    "additionalProperties": False,
}


class ToolInputError(ValueError):
    """The arguments do not satisfy the public MCP input contract."""


class ToolExecutionError(RuntimeError):
    """A sanitized tool-visible processing error."""


@dataclass(frozen=True)
class GhostToolResult:
    """Internal result returned from the tool to the MCP server adapter."""

    content: list[dict[str, str]]
    structuredContent: dict[str, str]
    isError: bool = False


def validate_arguments(
    arguments: Mapping[str, Any] | None,
) -> tuple[str, str | None]:
    """Validate and return the prompt text and optional supportive context."""
    if not isinstance(arguments, Mapping):
        raise ToolInputError(
            "prompt_text is required and must be a non-empty string"
        )

    unsupported = set(arguments).difference(
        {"prompt_text", "supportive_context"}
    )
    if unsupported:
        raise ToolInputError("unsupported input property")

    if "prompt_text" not in arguments:
        raise ToolInputError(
            "prompt_text is required and must be a non-empty string"
        )

    prompt_text = arguments["prompt_text"]
    if not isinstance(prompt_text, str) or not prompt_text.strip():
        raise ToolInputError("prompt_text must be a non-empty string")

    supportive_context = arguments.get("supportive_context")
    if supportive_context is not None and not isinstance(
        supportive_context,
        str,
    ):
        raise ToolInputError("supportive_context must be a string")

    if isinstance(supportive_context, str) and not supportive_context.strip():
        supportive_context = None

    return prompt_text, supportive_context


class GhostEngineerPromptTool:
    """Thin MCP adapter for the approved prompt-engineering use case."""

    def __init__(self, runner: PromptEngineeringRunner) -> None:
        """Store the existing GHOST prompt-engineering runner."""
        self._runner = runner

    def call(self, arguments: Mapping[str, Any] | None) -> GhostToolResult:
        """Select the response mode and execute prompt engineering."""
        raw_prompt_text, supportive_context = validate_arguments(arguments)
        prompt_text, mode = self._select_mode(raw_prompt_text)

        if (
            mode == ANSWER_PROMPT_WITH_MEMORY_MODE
            and supportive_context is None
        ):
            raise ToolInputError(
                "MEM: was requested, but ChatGPT did not supply "
                "supportive_context. Refresh the GHOST Local tool metadata, "
                "start a new conversation, and retry."
            )

        if (
            supportive_context is not None
            and mode != ANSWER_PROMPT_WITH_MEMORY_MODE
        ):
            raise ToolInputError(
                "supportive_context is allowed only when prompt_text begins "
                "with MEM:"
            )

        try:
            engineered_prompt = self._runner.run(prompt_text)
        except PromptEngineeringError as exc:
            raise ToolExecutionError(str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            raise ToolExecutionError("GHOST prompt engineering failed") from exc

        if mode == ANSWER_PROMPT_WITH_MEMORY_MODE:
            assert supportive_context is not None
            engineered_prompt = self._append_supportive_context(
                engineered_prompt,
                supportive_context,
            )

        return GhostToolResult(
            content=[{"type": "text", "text": engineered_prompt}],
            structuredContent={
                "engineered_prompt": engineered_prompt,
                "stage": "a2",
                "mode": mode,
            },
        )

    def call_sanitized(
        self,
        arguments: Mapping[str, Any] | None,
    ) -> GhostToolResult:
        """Execute the tool and convert expected failures to safe results."""
        try:
            return self.call(arguments)
        except (ToolInputError, ToolExecutionError) as exc:
            return GhostToolResult(
                content=[{"type": "text", "text": str(exc)}],
                structuredContent={},
                isError=True,
            )

    @staticmethod
    def _select_mode(prompt_text: str) -> tuple[str, str]:
        """Select the mode only from an optional leading Prompt or MEM prefix."""
        prompt_match = PROMPT_MODE_PREFIX.match(prompt_text)
        if prompt_match is not None:
            return (
                prompt_text[prompt_match.end():].strip(),
                SHOW_PROMPT_ONLY_MODE,
            )

        memory_match = MEMORY_MODE_PREFIX.match(prompt_text)
        if memory_match is not None:
            return (
                prompt_text[memory_match.end():].strip(),
                ANSWER_PROMPT_WITH_MEMORY_MODE,
            )

        return prompt_text, ANSWER_PROMPT_MODE

    @staticmethod
    def _append_supportive_context(
        engineered_prompt: str,
        supportive_context: str,
    ) -> str:
        """Append the previous assistant response without sending it through A2."""
        return (
            f"{engineered_prompt.rstrip()}\n\n"
            f"## Supportive Context\n\n{supportive_context.strip()}"
        )


def tool_metadata(required_scope: str | None = None) -> dict[str, Any]:
    """Build the OAuth-protected MCP tool descriptor."""
    scope = (
        required_scope
        if required_scope is not None
        else DEFAULT_REQUIRED_SCOPE
    ).strip()
    if not scope:
        raise ValueError("required_scope must not be empty")

    security_schemes = [{"type": "oauth2", "scopes": [scope]}]
    compatibility_security_schemes = [{"type": "oauth2", "scopes": [scope]}]

    return {
        "name": TOOL_NAME,
        "title": TOOL_TITLE,
        "description": TOOL_DESCRIPTION,
        "inputSchema": INPUT_SCHEMA,
        "outputSchema": OUTPUT_SCHEMA,
        "securitySchemes": security_schemes,
        "_meta": {
            "securitySchemes": compatibility_security_schemes,
        },
        "annotations": {
            "destructiveHint": False,
            "readOnlyHint": True,
            "idempotentHint": False,
        },
    }