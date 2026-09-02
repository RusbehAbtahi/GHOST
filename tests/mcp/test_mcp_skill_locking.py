"""Focused tests for domain-separated MCP Skill locks."""

from pathlib import Path

from ragstream.mcp.mcp_skill_maker import McpSkillMakerTool
from ragstream.memory.mcp_skill_memory_store import resolve_skill_domain


def test_same_skill_can_lock_independently_in_each_domain(
    tmp_path: Path,
) -> None:
    tool = McpSkillMakerTool(skills_base_root=tmp_path)
    cli_root = resolve_skill_domain("CLI").skills_root(tmp_path)
    general_root = resolve_skill_domain("GENERAL").skills_root(
        tmp_path
    )

    cli_locks = tool._acquire_locks(
        cli_root,
        "owner-1",
        "shared-name",
        ["shared-id"],
    )
    general_locks = tool._acquire_locks(
        general_root,
        "owner-1",
        "shared-name",
        ["shared-id"],
    )

    assert cli_locks is not None
    assert general_locks is not None
    tool._release_locks(general_locks)
    tool._release_locks(cli_locks)

    assert (
        cli_root / ".locks" / "owner-1" / "id_shared-id.lock"
    ).is_file()
    assert (
        general_root / ".locks" / "owner-1" / "id_shared-id.lock"
    ).is_file()
