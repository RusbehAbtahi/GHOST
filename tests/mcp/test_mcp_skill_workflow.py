"""End-to-end acceptance tests for the GHOST MCP Skill workflow.

These tests connect the real MCP Skill adapters to real request-scoped
SkillManager instances. Only the external Memory persistence is replaced by
a small in-memory implementation so the tests remain fast and deterministic.

The complete workflow covered here is:

1. Create a new Skill through ghost_skill_make.
2. Retrieve its description through ghost_skill_loader.
3. Load its complete SKILL.md through its exact Skill ID.
4. Create an immutable replacement Skill.
5. Archive and exclude the replaced Skill.
6. Retrieve only the new active replacement.
7. Enforce owner isolation.
8. Reject concurrent updates through the non-waiting Linux Skill lock.

These are acceptance tests. The smaller unit tests in tests/skills and
tests/mcp/test_mcp_skills.py remain responsible for individual validation
rules and isolated adapter behavior.
"""

from __future__ import annotations

import fcntl

from pathlib import Path
from typing import Any

from ragstream.mcp.mcp_skill_loader import McpSkillLoaderTool
from ragstream.mcp.mcp_skill_maker import (
    CREATE_NEW_SKILL,
    SKILL_UPDATE_BUSY,
    UPDATE_EXISTING_SKILL,
    McpSkillMakerTool,
)
from ragstream.skills.skill_manager import SkillManager


OWNER_ONE = "owner-1"
OWNER_TWO = "owner-2"


class InMemorySkillStore:
    """Provide deterministic owner-scoped persistence for workflow tests."""

    def __init__(self) -> None:
        self._records: dict[str, dict[str, dict[str, Any]]] = {}
        self._record_sequence = 0

    def save_skill(
        self,
        *,
        owner_sub: str,
        skill_data: dict[str, Any],
    ) -> dict[str, str]:
        """Persist one active Skill using its GHOST-generated Skill ID."""
        owner_records = self._records.setdefault(owner_sub, {})
        skill_id = str(skill_data["skill_id"])

        if skill_id in owner_records:
            raise ValueError(f"Skill already exists: {skill_id}")

        self._record_sequence += 1
        record_id = f"record-{self._record_sequence}"
        stored_data = dict(skill_data)
        stored_data["notes"] = list(skill_data.get("notes", []))
        stored_data["ragmem_record_id"] = record_id
        stored_data["ragmem_recall_key"] = str(
            skill_data["ragmem_recall_key"]
        )
        owner_records[skill_id] = stored_data

        return {
            "file_id": f"CLI_SKILL-{owner_sub}",
            "record_id": record_id,
            "recall_key": stored_data["ragmem_recall_key"],
        }

    def search_skills(
        self,
        *,
        owner_sub: str,
        query: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        """Return active descriptions in deterministic creation order."""
        if not query.strip():
            raise ValueError("query must not be empty")

        owner_records = self._records.get(owner_sub, {})
        active_records = [
            record
            for record in owner_records.values()
            if str(record.get("skill_status", "")).upper() == "ACTIVE"
        ]

        # Vector ranking itself has focused unit tests. This acceptance store
        # supplies a stable similarity so this test can verify the complete
        # MCP-to-SkillManager workflow without an external embedding service.
        return [
            {
                "skill_id": str(record["skill_id"]),
                "skill_description": str(
                    record["skill_description"]
                ),
                "skill_status": "ACTIVE",
                "cosine_similarity": 0.95,
            }
            for record in active_records[:limit]
        ]

    def get_skill(
        self,
        *,
        owner_sub: str,
        skill_id: str,
        active_only: bool = False,
    ) -> dict[str, Any] | None:
        """Return one exact owner-scoped Skill record."""
        record = self._records.get(owner_sub, {}).get(skill_id)
        if record is None:
            return None

        if (
            active_only
            and str(record.get("skill_status", "")).upper()
            != "ACTIVE"
        ):
            return None

        result = dict(record)
        result["notes"] = list(record.get("notes", []))
        return result

    def exclude_skills(
        self,
        *,
        owner_sub: str,
        archived_skills: list[dict[str, Any]],
    ) -> None:
        """Mark replaced Skill episodes EXCLUDED without deleting them."""
        owner_records = self._records.get(owner_sub, {})

        # Validate every requested ID before changing any record.
        records_to_exclude: list[
            tuple[dict[str, Any], dict[str, Any]]
        ] = []
        for archived_skill in archived_skills:
            skill_id = str(archived_skill["skill_id"])
            record = owner_records.get(skill_id)

            if record is None:
                raise ValueError(f"skill_id was not found: {skill_id}")
            if str(record.get("skill_status", "")).upper() != "ACTIVE":
                raise ValueError(f"Skill is not ACTIVE: {skill_id}")

            records_to_exclude.append((record, archived_skill))

        for record, archived_skill in records_to_exclude:
            record["skill_status"] = "EXCLUDED"
            record["folder_path"] = str(
                archived_skill["folder_path"]
            )
            record["skill_md_path"] = str(
                archived_skill["skill_md_path"]
            )
            record["notes"] = list(
                archived_skill.get("notes", [])
            )

    def active_skill_ids(self, owner_sub: str) -> list[str]:
        """Return active IDs for assertions without exposing internal state."""
        return [
            skill_id
            for skill_id, record in self._records.get(
                owner_sub,
                {},
            ).items()
            if str(record.get("skill_status", "")).upper() == "ACTIVE"
        ]

    def skill_count(self, owner_sub: str) -> int:
        """Return all preserved active and excluded Skill records."""
        return len(self._records.get(owner_sub, {}))


class RealManagerFactory:
    """Create fresh real SkillManager instances over shared persistence."""

    def __init__(
        self,
        *,
        skills_root: Path,
        memory_store: InMemorySkillStore,
    ) -> None:
        self._skills_root = skills_root
        self._memory_store = memory_store
        self.created_managers: list[SkillManager] = []

    def __call__(self, owner_sub: str) -> SkillManager:
        """Create one request-scoped manager for the authenticated owner."""
        manager = SkillManager(
            owner_sub=owner_sub,
            skills_root=self._skills_root,
            memory_store=self._memory_store,
        )
        self.created_managers.append(manager)
        return manager


def _skill_arguments(
    *,
    decision: str = CREATE_NEW_SKILL,
    affected_skill_ids: list[str] | None = None,
    description: str = (
        "Inspect filesystem folders using the smallest safe scope."
    ),
    instruction_text: str = (
        "Use Bash and inspect only the directory depth requested."
    ),
) -> dict[str, Any]:
    """Build one complete model-prepared Skill request."""
    return {
        "decision": decision,
        "skill_name": "filesystem-search",
        "skill_title": "GHOST Filesystem Search",
        "skill_description": description,
        "skill_text": instruction_text,
        "yaml_metadata": {
            "version": 1,
            "environment": "Bash/WSL",
        },
        "ragmem_title": "GHOST Filesystem Search",
        "ragmem_description": description,
        "affected_skill_ids": list(affected_skill_ids or []),
        "notes": [
            {
                "source": "Layer-1 CLI execution feedback",
            }
        ],
    }


def _create_tools(
    tmp_path: Path,
) -> tuple[
    McpSkillLoaderTool,
    McpSkillMakerTool,
    InMemorySkillStore,
    RealManagerFactory,
]:
    """Create real MCP adapters with fresh managers and shared storage."""
    memory_store = InMemorySkillStore()
    manager_factory = RealManagerFactory(
        skills_root=tmp_path,
        memory_store=memory_store,
    )

    loader = McpSkillLoaderTool(
        manager_factory=manager_factory,
    )
    maker = McpSkillMakerTool(
        manager_factory=manager_factory,
        skills_root=tmp_path,
    )
    return loader, maker, memory_store, manager_factory


def test_complete_create_load_and_replace_workflow(
    tmp_path: Path,
) -> None:
    """Verify the approved immutable Skill lifecycle end to end."""
    loader, maker, memory_store, manager_factory = _create_tools(
        tmp_path
    )

    create_result = maker.call_sanitized(
        OWNER_ONE,
        _skill_arguments(),
    )

    assert create_result.isError is False
    assert create_result.structuredContent["created"] is True
    assert (
        create_result.structuredContent["decision"]
        == CREATE_NEW_SKILL
    )
    assert create_result.structuredContent["affected_skill_ids"] == []

    original_skill_id = str(
        create_result.structuredContent["skill_id"]
    )
    original_folder = Path(
        create_result.structuredContent["folder_path"]
    )
    original_skill_path = Path(
        create_result.structuredContent["skill_md_path"]
    )

    assert original_skill_id
    assert original_folder.is_dir()
    assert original_skill_path.is_file()
    assert original_skill_path.parent == original_folder
    assert (
        original_folder.parent
        == tmp_path / OWNER_ONE
    )

    original_text = original_skill_path.read_text(
        encoding="utf-8"
    )
    assert original_text.startswith("---\n")
    assert "# GHOST Filesystem Search" in original_text
    assert (
        "Use Bash and inspect only the directory depth requested."
        in original_text
    )

    search_result = loader.call_sanitized(
        OWNER_ONE,
        {"query": "inspect Windows filesystem folders"},
    )

    assert search_result.isError is False
    assert (
        search_result.structuredContent["workflow_state"]
        == "selection_required"
    )
    assert search_result.structuredContent["candidate_count"] == 1

    candidate = search_result.structuredContent["candidates"][0]

    # Search returns only identification, Description, and vector score.
    assert set(candidate) == {
        "skill_id",
        "skill_description",
        "cosine_similarity",
    }
    assert candidate["skill_id"] == original_skill_id
    assert candidate["skill_description"] == (
        "Inspect filesystem folders using the smallest safe scope."
    )

    load_result = loader.call_sanitized(
        OWNER_ONE,
        {"skill_ids": [original_skill_id]},
    )

    assert load_result.isError is False
    assert load_result.structuredContent["loaded_count"] == 1
    assert load_result.structuredContent["skills"] == [
        {
            "skill_id": original_skill_id,
            "skill_text": original_text,
        }
    ]

    updated_description = (
        "Inspect Windows folders through Bash/WSL using shallow, "
        "read-only filesystem commands."
    )
    updated_instruction = (
        "Translate Windows paths to WSL mount paths. Use a shallow "
        "read-only find or ls command and never scan an entire drive "
        "when only immediate children were requested."
    )

    update_result = maker.call_sanitized(
        OWNER_ONE,
        _skill_arguments(
            decision=UPDATE_EXISTING_SKILL,
            affected_skill_ids=[original_skill_id],
            description=updated_description,
            instruction_text=updated_instruction,
        ),
    )

    assert update_result.isError is False
    assert update_result.structuredContent["created"] is True
    assert (
        update_result.structuredContent["decision"]
        == UPDATE_EXISTING_SKILL
    )
    assert update_result.structuredContent["affected_skill_ids"] == [
        original_skill_id
    ]

    replacement_skill_id = str(
        update_result.structuredContent["skill_id"]
    )
    replacement_skill_path = Path(
        update_result.structuredContent["skill_md_path"]
    )

    assert replacement_skill_id != original_skill_id
    assert replacement_skill_path.is_file()
    assert updated_instruction in replacement_skill_path.read_text(
        encoding="utf-8"
    )

    # The original immutable artifact was moved to the owner's Archive.
    assert not original_folder.exists()

    archived_record = memory_store.get_skill(
        owner_sub=OWNER_ONE,
        skill_id=original_skill_id,
        active_only=False,
    )
    assert archived_record is not None
    assert archived_record["skill_status"] == "EXCLUDED"

    archived_skill_path = Path(
        archived_record["skill_md_path"]
    )
    assert archived_skill_path.is_file()
    assert archived_skill_path.parent.parent.name == "Archive"

    # Retrieval must now expose only the active replacement.
    replacement_search = loader.call_sanitized(
        OWNER_ONE,
        {"query": "inspect Windows filesystem folders"},
    )

    assert replacement_search.isError is False
    assert replacement_search.structuredContent["candidate_count"] == 1
    assert replacement_search.structuredContent["candidates"] == [
        {
            "skill_id": replacement_skill_id,
            "skill_description": updated_description,
            "cosine_similarity": 0.95,
        }
    ]
    assert memory_store.active_skill_ids(OWNER_ONE) == [
        replacement_skill_id
    ]

    old_load_result = loader.call_sanitized(
        OWNER_ONE,
        {"skill_ids": [original_skill_id]},
    )

    assert old_load_result.isError is True
    assert "Active Skill was not found" in (
        old_load_result.structuredContent["reason"]
    )

    replacement_load = loader.call_sanitized(
        OWNER_ONE,
        {"skill_ids": [replacement_skill_id]},
    )

    assert replacement_load.isError is False
    assert updated_instruction in (
        replacement_load.structuredContent["skills"][0]["skill_text"]
    )

    # Every MCP call received a different request-scoped SkillManager.
    assert len(manager_factory.created_managers) == 7
    assert len(
        {
            id(manager)
            for manager in manager_factory.created_managers
        }
    ) == 7


def test_workflow_preserves_authenticated_owner_isolation(
    tmp_path: Path,
) -> None:
    """Ensure one owner cannot search or load another owner's Skills."""
    loader, maker, memory_store, _manager_factory = _create_tools(
        tmp_path
    )

    create_result = maker.call_sanitized(
        OWNER_ONE,
        _skill_arguments(),
    )
    owner_one_skill_id = str(
        create_result.structuredContent["skill_id"]
    )

    owner_two_search = loader.call_sanitized(
        OWNER_TWO,
        {"query": "inspect filesystem folders"},
    )

    assert owner_two_search.isError is False
    assert (
        owner_two_search.structuredContent["workflow_state"]
        == "complete"
    )
    assert owner_two_search.structuredContent["candidate_count"] == 0
    assert owner_two_search.structuredContent["candidates"] == []

    owner_two_load = loader.call_sanitized(
        OWNER_TWO,
        {"skill_ids": [owner_one_skill_id]},
    )

    assert owner_two_load.isError is True
    assert "Active Skill was not found" in (
        owner_two_load.structuredContent["reason"]
    )

    assert memory_store.skill_count(OWNER_ONE) == 1
    assert memory_store.skill_count(OWNER_TWO) == 0
    assert (
        tmp_path
        / OWNER_ONE
        / (
            "filesystem-search_"
            f"{owner_one_skill_id}"
        )
        / "SKILL.md"
    ).is_file()
    assert not (tmp_path / OWNER_TWO).exists()


def test_busy_update_aborts_then_succeeds_after_lock_release(
    tmp_path: Path,
) -> None:
    """Verify non-waiting locking without deleting the stable lock file."""
    _loader, maker, memory_store, _manager_factory = _create_tools(
        tmp_path
    )

    create_result = maker.call_sanitized(
        OWNER_ONE,
        _skill_arguments(),
    )
    original_skill_id = str(
        create_result.structuredContent["skill_id"]
    )

    lock_root = tmp_path / ".locks"
    lock_root.mkdir(parents=True, exist_ok=True)
    lock_path = (
        lock_root
        / f"{OWNER_ONE}_{original_skill_id}.lock"
    )

    update_arguments = _skill_arguments(
        decision=UPDATE_EXISTING_SKILL,
        affected_skill_ids=[original_skill_id],
        description=(
            "Updated filesystem instructions after concrete CLI feedback."
        ),
        instruction_text=(
            "Use one shallow Bash/WSL read-only command for this task."
        ),
    )

    # Simulate a parallel chat that is already updating this exact Skill.
    with lock_path.open("a+", encoding="utf-8") as held_lock:
        fcntl.flock(
            held_lock.fileno(),
            fcntl.LOCK_EX,
        )
        busy_result = maker.call_sanitized(
            OWNER_ONE,
            update_arguments,
        )
        fcntl.flock(
            held_lock.fileno(),
            fcntl.LOCK_UN,
        )

    assert busy_result.isError is True
    assert busy_result.structuredContent["created"] is False
    assert (
        busy_result.structuredContent["error_code"]
        == SKILL_UPDATE_BUSY
    )

    # The rejected parallel update created no replacement artifact or record.
    assert memory_store.skill_count(OWNER_ONE) == 1
    assert memory_store.active_skill_ids(OWNER_ONE) == [
        original_skill_id
    ]

    # After Linux releases the lock, a later update can proceed normally.
    successful_result = maker.call_sanitized(
        OWNER_ONE,
        update_arguments,
    )

    assert successful_result.isError is False
    assert successful_result.structuredContent["created"] is True
    assert (
        successful_result.structuredContent["decision"]
        == UPDATE_EXISTING_SKILL
    )
    assert successful_result.structuredContent[
        "affected_skill_ids"
    ] == [original_skill_id]

    replacement_skill_id = str(
        successful_result.structuredContent["skill_id"]
    )
    assert replacement_skill_id != original_skill_id
    assert memory_store.skill_count(OWNER_ONE) == 2
    assert memory_store.active_skill_ids(OWNER_ONE) == [
        replacement_skill_id
    ]

    # The file permanently identifies this lock subject. Its active lock
    # state is held and released internally by Linux.
    assert lock_path.is_file()

    with lock_path.open("a+", encoding="utf-8") as available_lock:
        fcntl.flock(
            available_lock.fileno(),
            fcntl.LOCK_EX | fcntl.LOCK_NB,
        )
        fcntl.flock(
            available_lock.fileno(),
            fcntl.LOCK_UN,
        )
