"""Focused tests for the Part 2 MCP Skill adapters and registration."""

from __future__ import annotations

import fcntl

from pathlib import Path
from typing import Any

from ragstream.mcp.ghost_engineer_prompt import GhostToolResult
from ragstream.mcp.ghost_mcp_app import GhostMcpApplication
from ragstream.mcp.mcp_skill_loader import (
    TOOL_NAME as SKILL_LOADER_TOOL_NAME,
    McpSkillLoaderTool,
    tool_metadata as skill_loader_metadata,
)
from ragstream.mcp.mcp_skill_maker import (
    CREATE_NEW_SKILL,
    SKILL_UPDATE_BUSY,
    TOOL_NAME as SKILL_MAKER_TOOL_NAME,
    UPDATE_EXISTING_SKILL,
    McpSkillMakerTool,
    tool_metadata as skill_maker_metadata,
)
from ragstream.skills.skill import Skill


class FakeSkillManager:
    """Record observable adapter calls without using disk or vector storage."""

    def __init__(self, owner_sub: str) -> None:
        self.owner_sub = owner_sub
        self.loaded_ids: list[str] = []
        self.archived_ids: list[str] = []
        self.created_skill: Skill | None = None
        self.candidates = [
            {
                "skill_id": "skill-old",
                "skill_description": "Search folders safely.",
                "cosine_similarity": 0.91,
            }
        ]

    def retrieve_candidates(self, query: str) -> list[dict[str, Any]]:
        assert query == "search folders"
        return list(self.candidates)

    def load_selected_skills(self, skill_ids: list[str]) -> list[str]:
        self.loaded_ids = list(skill_ids)
        return [f"# Loaded {skill_id}" for skill_id in skill_ids]

    def create_skill_artifact(self, skill: Skill) -> tuple[Skill, bool]:
        skill.skill_id = "skill-new"
        skill.folder_path = "/skills/owner-1/search_skill-new"
        skill.skill_md_path = f"{skill.folder_path}/SKILL.md"
        skill.skill_status = "ACTIVE"
        self.created_skill = skill
        return skill, True

    def persist_skill_memory(self, skill: Skill) -> Skill:
        skill.ragmem_record_id = "record-new"
        skill.ragmem_recall_key = skill.skill_id
        return skill

    def archive_replaced_skills(self, skill_ids: list[str]) -> None:
        self.archived_ids = list(skill_ids)


class RecordingManagerFactory:
    """Create and retain one FakeSkillManager for each adapter call."""

    def __init__(self) -> None:
        self.managers: list[FakeSkillManager] = []

    def __call__(self, owner_sub: str) -> FakeSkillManager:
        manager = FakeSkillManager(owner_sub)
        self.managers.append(manager)
        return manager


def _maker_arguments(
    decision: str = CREATE_NEW_SKILL,
    affected_skill_ids: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "decision": decision,
        "skill_name": "safe_search",
        "skill_title": "Safe Search",
        "skill_description": "Search folders safely.",
        "skill_text": "Use a shallow read-only search first.",
        "yaml_metadata": {"version": 1},
        "ragmem_title": "Safe folder search",
        "ragmem_description": "Reusable safe folder search rules.",
        "affected_skill_ids": affected_skill_ids or [],
        "notes": [{"source": "CLI feedback"}],
    }


def test_loader_search_returns_description_candidates() -> None:
    factory = RecordingManagerFactory()
    tool = McpSkillLoaderTool(manager_factory=factory)  # type: ignore[arg-type]

    result = tool.call_sanitized(
        "owner-1",
        {"query": "search folders"},
    )

    assert result.isError is False
    assert result.structuredContent == {
        "workflow_state": "selection_required",
        "query": "search folders",
        "candidate_count": 1,
        "candidates": factory.managers[0].candidates,
    }
    assert [manager.owner_sub for manager in factory.managers] == [
        "owner-1"
    ]


def test_loader_loads_exact_selected_skill_ids() -> None:
    factory = RecordingManagerFactory()
    tool = McpSkillLoaderTool(manager_factory=factory)  # type: ignore[arg-type]

    result = tool.call_sanitized(
        "owner-1",
        {"skill_ids": ["skill-old", "skill-second"]},
    )

    assert result.isError is False
    assert result.structuredContent["workflow_state"] == "complete"
    assert result.structuredContent["skills"] == [
        {
            "skill_id": "skill-old",
            "skill_text": "# Loaded skill-old",
        },
        {
            "skill_id": "skill-second",
            "skill_text": "# Loaded skill-second",
        },
    ]
    assert factory.managers[0].loaded_ids == [
        "skill-old",
        "skill-second",
    ]


def test_loader_creates_a_fresh_manager_for_every_call() -> None:
    factory = RecordingManagerFactory()
    tool = McpSkillLoaderTool(manager_factory=factory)  # type: ignore[arg-type]

    tool.call_sanitized("owner-1", {"query": "search folders"})
    tool.call_sanitized("owner-1", {"query": "search folders"})

    assert len(factory.managers) == 2
    assert factory.managers[0] is not factory.managers[1]


def test_loader_rejects_mixed_search_and_load_input() -> None:
    tool = McpSkillLoaderTool()

    result = tool.call_sanitized(
        "owner-1",
        {
            "query": "search folders",
            "skill_ids": ["skill-old"],
        },
    )

    assert result.isError is True
    assert "exactly one" in result.structuredContent["reason"]


def test_maker_creates_new_skill_without_archiving() -> None:
    factory = RecordingManagerFactory()
    tool = McpSkillMakerTool(manager_factory=factory)  # type: ignore[arg-type]

    result = tool.call_sanitized(
        "owner-1",
        _maker_arguments(),
    )

    manager = factory.managers[0]
    assert result.isError is False
    assert result.structuredContent["created"] is True
    assert result.structuredContent["skill_id"] == "skill-new"
    assert result.structuredContent["affected_skill_ids"] == []
    assert manager.created_skill is not None
    assert manager.created_skill.instruction_text == (
        "Use a shallow read-only search first."
    )
    assert manager.archived_ids == []


def test_maker_validates_then_archives_exact_replaced_ids(
    tmp_path: Path,
) -> None:
    factory = RecordingManagerFactory()
    tool = McpSkillMakerTool(
        manager_factory=factory,  # type: ignore[arg-type]
        skills_root=tmp_path,
    )

    result = tool.call_sanitized(
        "owner-1",
        _maker_arguments(
            UPDATE_EXISTING_SKILL,
            ["skill-old"],
        ),
    )

    manager = factory.managers[0]
    assert result.isError is False
    assert manager.loaded_ids == ["skill-old"]
    assert manager.archived_ids == ["skill-old"]

    # The stable file remains, but the adapter released Linux's lock state.
    lock_path = tmp_path / ".locks" / "owner-1_skill-old.lock"
    assert lock_path.is_file()
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        fcntl.flock(
            lock_file.fileno(),
            fcntl.LOCK_EX | fcntl.LOCK_NB,
        )
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def test_maker_aborts_immediately_when_replacement_is_locked(
    tmp_path: Path,
) -> None:
    lock_root = tmp_path / ".locks"
    lock_root.mkdir(parents=True)
    lock_path = lock_root / "owner-1_skill-old.lock"
    factory = RecordingManagerFactory()
    tool = McpSkillMakerTool(
        manager_factory=factory,  # type: ignore[arg-type]
        skills_root=tmp_path,
    )

    with lock_path.open("a+", encoding="utf-8") as held_lock:
        fcntl.flock(held_lock.fileno(), fcntl.LOCK_EX)
        result = tool.call_sanitized(
            "owner-1",
            _maker_arguments(
                UPDATE_EXISTING_SKILL,
                ["skill-old"],
            ),
        )
        fcntl.flock(held_lock.fileno(), fcntl.LOCK_UN)

    assert result.isError is True
    assert result.structuredContent["error_code"] == SKILL_UPDATE_BUSY
    assert factory.managers == []


def test_maker_rejects_incoherent_decision_and_ids() -> None:
    tool = McpSkillMakerTool()

    result = tool.call_sanitized(
        "owner-1",
        _maker_arguments(CREATE_NEW_SKILL, ["skill-old"]),
    )

    assert result.isError is True
    assert "requires empty" in result.structuredContent["reason"]


def test_skill_metadata_has_expected_read_and_write_hints() -> None:
    loader = skill_loader_metadata("ghost.use")
    maker = skill_maker_metadata("ghost.use")

    assert loader["name"] == SKILL_LOADER_TOOL_NAME
    assert loader["annotations"]["readOnlyHint"] is True
    assert loader["annotations"]["idempotentHint"] is True
    assert maker["name"] == SKILL_MAKER_TOOL_NAME
    assert maker["annotations"]["readOnlyHint"] is False
    assert maker["annotations"]["idempotentHint"] is False


def test_application_registers_both_skill_tools() -> None:
    # list_tools only needs required_scope. Avoid creating unrelated stores in
    # this focused registration test.
    application = GhostMcpApplication.__new__(GhostMcpApplication)
    application.required_scope = "ghost.use"

    tool_names = [tool.name for tool in application.list_tools()]

    assert SKILL_LOADER_TOOL_NAME in tool_names
    assert SKILL_MAKER_TOOL_NAME in tool_names


def test_application_dispatches_skill_loader_with_authenticated_owner() -> None:
    class RecordingSkillTool:
        def __init__(self) -> None:
            self.call: tuple[str, Any] | None = None

        def call_sanitized(
            self,
            owner_sub: str,
            arguments: Any,
        ) -> GhostToolResult:
            self.call = (owner_sub, arguments)
            return GhostToolResult(
                content=[{"type": "text", "text": "loaded"}],
                structuredContent={"workflow_state": "complete"},
            )

    application = GhostMcpApplication.__new__(GhostMcpApplication)
    recording_tool = RecordingSkillTool()
    application.skill_loader_tool = recording_tool

    result = application.call_tool(
        SKILL_LOADER_TOOL_NAME,
        {"query": "search folders"},
        owner_sub="owner-1",
    )

    assert result.isError is False
    assert result.structuredContent == {"workflow_state": "complete"}
    assert recording_tool.call == (
        "owner-1",
        {"query": "search folders"},
    )