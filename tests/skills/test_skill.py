from ragstream.skills.skill import Skill


def _complete_skill() -> Skill:
    return Skill(
        skill_id="skill-1",
        skill_name="filesystem-search",
        skill_title="Filesystem Search",
        skill_description=(
            "Search folders with the smallest safe scope."
        ),
        folder_path=(
            "data/skills/MCP_CLI/owner/filesystem-search"
        ),
        skill_md_path=(
            "data/skills/MCP_CLI/owner/"
            "filesystem-search/SKILL.md"
        ),
        yaml_metadata={
            "name": "filesystem-search",
            "description": "Search folders safely.",
        },
        instruction_text=(
            "Use depth-limited find for shallow searches."
        ),
        ragmem_record_id="record-1",
        ragmem_recall_key="skill-1",
        ragmem_title="Filesystem Search",
        ragmem_description="Search folders safely.",
        ragmem_q=(
            "data/skills/MCP_CLI/owner/"
            "filesystem-search/SKILL.md"
        ),
        ragmem_a='{"skill_id": "skill-1"}',
        skill_status="ACTIVE",
        notes=[],
    )


def test_validate_accepts_complete_skill() -> None:
    assert _complete_skill().validate() == []


def test_validate_reports_missing_and_incoherent_fields() -> None:
    skill = _complete_skill()
    skill.skill_id = ""
    skill.skill_md_path = "wrong-name.md"
    skill.skill_status = "UNKNOWN"

    errors = skill.validate()

    assert "skill_id must not be empty." in errors
    assert "skill_md_path must point to SKILL.md." in errors
    assert (
        "skill_status must be ACTIVE or EXCLUDED."
        in errors
    )