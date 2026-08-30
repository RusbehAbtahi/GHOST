from pathlib import Path

from ragstream.skills.skill import Skill
from ragstream.skills.skill_creator import SkillCreator


def _new_skill(folder_path: Path) -> Skill:
    return Skill(
        skill_id="skill-1",
        skill_name="filesystem-search",
        skill_title="Filesystem Search",
        skill_description="Search folders safely.",
        folder_path=str(folder_path),
        yaml_metadata={},
        instruction_text=(
            "Use the smallest sufficient search scope."
        ),
        notes=[],
    )


def test_create_skill_writes_standard_skill_artifact(
    tmp_path: Path,
) -> None:
    skill = _new_skill(
        tmp_path / "owner" / "filesystem-search"
    )

    created, success = SkillCreator().create_skill(skill)

    assert success is True
    assert created.skill_status == "ACTIVE"
    assert created.skill_md_path.endswith("SKILL.md")
    assert created.ragmem_q == created.skill_md_path
    assert '"skill_id": "skill-1"' in created.ragmem_a

    content = Path(created.skill_md_path).read_text(
        encoding="utf-8"
    )
    assert content.startswith("---\n")
    assert '"name": "filesystem-search"' in content
    assert "# Filesystem Search" in content
    assert (
        "Use the smallest sufficient search scope."
        in content
    )


def test_create_skill_does_not_overwrite_existing_folder(
    tmp_path: Path,
) -> None:
    folder = tmp_path / "owner" / "filesystem-search"
    folder.mkdir(parents=True)

    existing_file = folder / "SKILL.md"
    existing_file.write_text(
        "existing",
        encoding="utf-8",
    )

    _created, success = SkillCreator().create_skill(
        _new_skill(folder)
    )

    assert success is False
    assert (
        existing_file.read_text(encoding="utf-8")
        == "existing"
    )