from __future__ import annotations

import threading
import pytest

from ragstream.mcp.auth import AuthConfig, ConfigurableTokenVerifier, authenticate_request, AuthenticationError
from ragstream.mcp.ghost_engineer_prompt import GhostEngineerPromptTool, ToolInputError, validate_arguments
from ragstream.mcp.prompt_engineering_runner import PromptEngineeringRunner
from ragstream.mcp.rate_limiter import InMemoryRateLimiter
from ragstream.mcp.server import GhostMcpApplication, McpInvocationBoundary


class Schema:
    pass


def test_runner_order_same_fresh_superprompt_and_stage_gate():
    calls = []
    seen = []

    class SP:
        def __init__(self):
            self.stage = "raw"
            self.prompt_ready = ""
            seen.append(self)

    def pp(text, sp, schema):
        calls.append(("pre", text, id(sp)))
        sp.stage = "preprocessed"

    class A2:
        def __init__(self, factory, client):
            pass
        def run(self, sp, *, agent_id, version, use_llm):
            calls.append(("a2", agent_id, version, use_llm, id(sp)))
            assert sp.stage == "preprocessed"
            sp.stage = "a2"
            sp.prompt_ready = "ENGINEERED"
            return sp

    runner = PromptEngineeringRunner(schema=Schema(), super_prompt_factory=SP, preprocess_func=pp, agent_factory=object(), llm_client=object(), a2_factory=A2)
    assert runner.run("hello") == "ENGINEERED"
    assert len(seen) == 1
    assert calls == [("pre", "hello", id(seen[0])), ("a2", "a2_promptshaper", "003", True, id(seen[0]))]


def test_request_isolation_for_simultaneous_prompts():
    barrier = threading.Barrier(2)
    seen_ids = []
    results = []

    class SP:
        def __init__(self):
            self.stage = "raw"
            self.prompt_ready = ""

    def pp(text, sp, schema):
        sp.text = text
        seen_ids.append(id(sp))
        barrier.wait(timeout=5)
        sp.stage = "preprocessed"

    class A2:
        def __init__(self, factory, client): pass
        def run(self, sp, **kwargs):
            sp.stage = "a2"
            sp.prompt_ready = f"out:{sp.text}"
            return sp

    runner = PromptEngineeringRunner(schema=Schema(), super_prompt_factory=SP, preprocess_func=pp, agent_factory=object(), llm_client=object(), a2_factory=A2)
    threads = [threading.Thread(target=lambda p=p: results.append(runner.run(p))) for p in ["one", "two"]]
    for t in threads: t.start()
    for t in threads: t.join()
    assert sorted(results) == ["out:one", "out:two"]
    assert len(set(seen_ids)) == 2


def test_input_validation_preserves_unicode_markdown_and_rejects_bad_inputs():
    text = "# TASK\nحافظ على Markdown ✅\n## CONTEXT\nLine two"
    assert validate_arguments({"prompt_text": text}) == text
    for args in [None, {}, {"prompt_text": "   "}, {"prompt_text": 3}, {"prompt_text": "x", "extra": "no"}]:
        with pytest.raises(ToolInputError):
            validate_arguments(args)


def test_output_contract_exact_text_and_structured_content():
    class Runner:
        def run(self, prompt_text):
            return "## TASK\nengineered"
    result = GhostEngineerPromptTool(Runner()).call({"prompt_text": "x"})
    assert result.isError is False
    assert result.content == [{"type": "text", "text": "## TASK\nengineered"}]
    assert result.structuredContent == {"engineered_prompt": "## TASK\nengineered", "stage": "a2"}


def test_tool_discovery_exactly_one_tool():
    app = GhostMcpApplication(tool=GhostEngineerPromptTool(type("R", (), {"run": lambda self, p: "ok"})()))
    tools = app.list_tools()
    assert [tool["name"] for tool in tools] == ["ghost_engineer_prompt"]
    assert tools[0]["inputSchema"]["additionalProperties"] is False


def test_sanitized_failure_hides_stack_secret_raw_output_and_path():
    class Runner:
        def run(self, prompt_text):
            raise RuntimeError("/tmp/secret OPENAI_API_KEY raw model output Traceback")
    result = GhostEngineerPromptTool(Runner()).call_sanitized({"prompt_text": "x"})
    assert result.isError is True
    message = result.content[0]["text"]
    assert message == "GHOST prompt engineering failed"
    assert "OPENAI" not in message and "Traceback" not in message and "/tmp" not in message


def test_rate_limited_call_does_not_reach_runner():
    calls = []
    class Runner:
        def run(self, prompt_text):
            calls.append(prompt_text)
            return "ok"
    limiter = InMemoryRateLimiter(limit=1, window_seconds=60, clock=lambda: 1.0)
    app = GhostMcpApplication(tool=GhostEngineerPromptTool(Runner()), boundary=McpInvocationBoundary(rate_limiter=limiter))
    assert app.call_tool("ghost_engineer_prompt", {"prompt_text": "one"}).structuredContent["engineered_prompt"] == "ok"
    second = app.call_tool("ghost_engineer_prompt", {"prompt_text": "two"})
    assert second["status_code"] == 429
    assert calls == ["one"]


def test_authentication_boundary_blocks_ghost_processing():
    calls = []
    class Runner:
        def run(self, prompt_text):
            calls.append(prompt_text)
            return "ok"
    verifier = ConfigurableTokenVerifier(
        AuthConfig(issuer="issuer", resource="ghost", required_scopes=("prompt:engineer",)),
        decoder=lambda token: {"sub": "u", "iss": "issuer", "aud": "ghost", "scope": "prompt:engineer", "exp": 4102444800} if token == "valid" else {},
    )
    app = GhostMcpApplication(tool=GhostEngineerPromptTool(Runner()), boundary=McpInvocationBoundary(verifier=verifier))
    assert app.call_tool("ghost_engineer_prompt", {"prompt_text": "x"}, authorization_header=None)["status_code"] == 401
    assert app.call_tool("ghost_engineer_prompt", {"prompt_text": "x"}, authorization_header="Bearer bad")["status_code"] == 401
    assert calls == []
    assert app.call_tool("ghost_engineer_prompt", {"prompt_text": "x"}, authorization_header="Bearer valid").structuredContent["engineered_prompt"] == "ok"
    assert calls == ["x"]
