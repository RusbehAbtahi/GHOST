from pathlib import Path
from typing import Any

from ragstream.skills.skill import Skill
from ragstream.skills.skill_manager import SkillManager


class FakeMemoryStore:
    def __init__(self) -> None:
        self.saved: dict[str, dict[str, Any]] = {}
        self.excluded: list[dict[str, Any]] = []

    def save_skill(
        self,
        *,
        owner_sub: str,
        skill_data: dict[str, Any],
        replacing_skill_ids: list[str] | None = None,
    ) -> dict[str, str]:
        self.saved[skill_data["skill_id"]] = dict(
            skill_data
        )
        return {
            "file_id": "file-1",
            "record_id": "record-1",
            "recall_key": skill_data[
                "ragmem_recall_key"
            ],
        }

    def search_skills(
        self,
        *,
        owner_sub: str,
        query: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        return []

    def get_skill(
        self,
        *,
        owner_sub: str,
        skill_id: str,
        active_only: bool,
    ) -> dict[str, Any] | None:
        item = self.saved.get(skill_id)
        if item is None:
            return None

        return {
            **item,
            "skill_status": "ACTIVE",
        }

    def exclude_skills(
        self,
        *,
        owner_sub: str,
        archived_skills: list[dict[str, Any]],
    ) -> None:
        self.excluded.extend(archived_skills)


def _prepared_skill() -> Skill:
    return Skill(
        skill_name="filesystem-search",
        skill_title="Filesystem Search",
        skill_description="Search folders safely.",
        yaml_metadata={},
        instruction_text=(
            "Use the smallest sufficient search scope."
        ),
        notes=[],
    )


def test_manager_creates_and_persists_skill(
    tmp_path: Path,
) -> None:
    store = FakeMemoryStore()
    manager = SkillManager(
        owner_sub="owner-1",
        skills_root=tmp_path,
        memory_store=store,
    )

    skill, created = manager.create_skill_artifact(
        _prepared_skill()
    )
    persisted = manager.persist_skill_memory(skill)

    assert created is True
    assert persisted.skill_id
    assert persisted.ragmem_record_id == "record-1"
    assert (
        persisted.ragmem_recall_key
        == persisted.skill_id
    )
    assert persisted.validate() == []
    assert manager.current_skill is None
    assert (
        manager.skills[persisted.skill_id]
        is persisted
    )
    assert (
        store.saved[persisted.skill_id][
            "skill_description"
        ]
        == "Search folders safely."
    )


def test_manager_archives_artifact_and_excludes_memory(
    tmp_path: Path,
) -> None:
    store = FakeMemoryStore()
    manager = SkillManager(
        owner_sub="owner-1",
        skills_root=tmp_path,
        memory_store=store,
    )

    skill, created = manager.create_skill_artifact(
        _prepared_skill()
    )
    assert created is True

    manager.persist_skill_memory(skill)
    original_folder = Path(skill.folder_path)

    manager.archive_replaced_skills(
        [skill.skill_id]
    )

    assert not original_folder.exists()
    assert Path(
        store.excluded[0]["skill_md_path"]
    ).is_file()
    assert skill.skill_status == "EXCLUDED"
    assert manager.affected_skill_ids == [
        skill.skill_id
    ]