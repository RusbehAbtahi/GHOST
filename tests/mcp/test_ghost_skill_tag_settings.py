"""Tests for the owner-scoped dynamic Skill tag settings interface."""

from __future__ import annotations

import json

from pathlib import Path

from ragstream.mcp.ghost_skill_tag_settings import GhostSkillTagSettingsTool
from ragstream.skills.skill_tags import (
    DEFAULT_SKILL_TAG_CATALOG_PATH,
    SkillTagCatalog,
)


def _catalog(tmp_path: Path) -> SkillTagCatalog:
    return SkillTagCatalog(settings_root=tmp_path / "skill_tag_settings")


def _approved_defaults() -> list[str]:
    return list(
        json.loads(
            DEFAULT_SKILL_TAG_CATALOG_PATH.read_text(encoding="utf-8")
        )["skill_tags"]
    )


def test_show_creates_persisted_catalog_from_approved_json_defaults(
    tmp_path: Path,
) -> None:
    catalog = _catalog(tmp_path)
    tool = GhostSkillTagSettingsTool(catalog, usage_checker=lambda *_: [])

    result = tool.call_sanitized("owner-1", {"action": "show"})

    assert result.isError is False
    assert result.structuredContent["skill_tags"] == _approved_defaults()
    persisted = json.loads(
        catalog.settings_path("owner-1").read_text(encoding="utf-8")
    )
    assert persisted["skill_tags"] == _approved_defaults()


def test_add_new_tag_changes_only_catalog_data(tmp_path: Path) -> None:
    catalog = _catalog(tmp_path)
    tool = GhostSkillTagSettingsTool(catalog, usage_checker=lambda *_: [])

    result = tool.call_sanitized(
        "owner-1",
        {"action": "add", "tag": "architecture"},
    )

    assert result.isError is False
    assert result.structuredContent["changed"] is True
    assert "ARCHITECTURE" in result.structuredContent["skill_tags"]
    assert "ARCHITECTURE" in catalog.tags("owner-1")


def test_remove_reports_usage_and_keeps_tag(tmp_path: Path) -> None:
    catalog = _catalog(tmp_path)
    catalog.add("owner-1", "ARCHITECTURE")
    usage = [
        {
            "skill_domain": "GENERAL",
            "skill_id": "skill-1",
            "skill_name": "architecture-guide",
            "skill_status": "ACTIVE",
        }
    ]
    tool = GhostSkillTagSettingsTool(
        catalog,
        usage_checker=lambda *_: list(usage),
    )

    result = tool.call_sanitized(
        "owner-1",
        {"action": "remove", "tag": "ARCHITECTURE"},
    )

    assert result.isError is False
    assert result.structuredContent["changed"] is False
    assert result.structuredContent["usage"] == usage
    assert "ARCHITECTURE" in catalog.tags("owner-1")


def test_remove_unused_tag_updates_catalog(tmp_path: Path) -> None:
    catalog = _catalog(tmp_path)
    catalog.add("owner-1", "ARCHITECTURE")
    tool = GhostSkillTagSettingsTool(catalog, usage_checker=lambda *_: [])

    result = tool.call_sanitized(
        "owner-1",
        {"action": "remove", "tag": "ARCHITECTURE"},
    )

    assert result.isError is False
    assert result.structuredContent["changed"] is True
    assert "ARCHITECTURE" not in catalog.tags("owner-1")


def test_application_registers_skill_tag_settings_tool() -> None:
    from ragstream.mcp.ghost_mcp_app import GhostMcpApplication
    from ragstream.mcp.ghost_skill_tag_settings import TOOL_NAME

    application = GhostMcpApplication.__new__(GhostMcpApplication)
    application.required_scope = "ghost.use"

    assert TOOL_NAME in [tool.name for tool in application.list_tools()]
