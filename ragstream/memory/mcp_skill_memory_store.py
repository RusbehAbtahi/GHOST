"""Persist and retrieve owner-scoped MCP CLI Skill Memory.

This module is a small Skill-specific adapter over the existing GHOST Memory
architecture. MemoryManager remains responsible for RagMem, RagMeta, and SQLite
bookkeeping. McpEpisodicDescriptionVectorStore remains responsible for Chroma
description vectors. SkillManager never accesses either persistence detail.
"""

from __future__ import annotations

import json
import re

from pathlib import Path
from typing import Any

from ragstream.memory.mcp_episodic_description_vector_store import (
    McpEpisodicDescriptionVectorStore,
)
from ragstream.memory.memory_manager import MemoryManager
from ragstream.memory.memory_record import MemoryRecord


CLI_SKILL_MEMORY_TYPE = "cli_skill"
CLI_SKILL_TITLE = "CLI_SKILL"
CLI_SKILL_DESCRIPTION = "Owner-scoped MCP CLI Skill descriptions."
DEFAULT_MEMORY_ROOT = Path("data/mcp/memory")
_SAFE_OWNER_SUB = re.compile(r"[A-Za-z0-9._-]+")
ACTIVE_SKILL_STATUS = "ACTIVE"
PENDING_SKILL_STATUS = "PENDING"
EXCLUDED_SKILL_STATUS = "EXCLUDED"


class SkillNameAlreadyExistsError(ValueError):
    """Report an exact owner-scoped ACTIVE Skill-name conflict."""

    def __init__(self, skill_name: str, existing_skill_id: str) -> None:
        self.skill_name = skill_name
        self.existing_skill_id = existing_skill_id
        super().__init__(
            f"ACTIVE skill_name already exists: {skill_name} "
            f"({existing_skill_id})"
        )


class SkillRegistryIntegrityError(ValueError):
    """Report a pre-existing duplicate ACTIVE Skill-name state."""


class McpSkillMemoryStore:
    """Own Skill RagMem, RagMeta, SQLite, and vector persistence."""

    def __init__(
        self,
        memory_root: str | Path = DEFAULT_MEMORY_ROOT,
        sqlite_path: str | Path | None = None,
        description_vector_store: (
            McpEpisodicDescriptionVectorStore | None
        ) = None,
    ) -> None:
        self.memory_root = Path(memory_root)
        self.sqlite_path = (
            Path(sqlite_path)
            if sqlite_path is not None
            else self.memory_root / "memory_index.sqlite3"
        )
        self.vector_root = self.memory_root / "vector_db"
        self._description_vectors = (
            description_vector_store
            if description_vector_store is not None
            else McpEpisodicDescriptionVectorStore(
                self.vector_root
            )
        )

    def save_skill(
        self,
        *,
        owner_sub: str,
        skill_data: dict[str, Any],
        replacing_skill_ids: list[str] | None = None,
    ) -> dict[str, str]:
        """Persist a new ACTIVE Skill or a staged replacement Skill."""
        owner = self._validate_owner_sub(owner_sub)
        data = self._validated_skill_data(skill_data)
        replacing_ids = self._clean_skill_ids(
            replacing_skill_ids or []
        )
        manager = self._load_or_create_manager(owner)
        self._assert_active_name_integrity(manager)

        if self._find_record(manager, data["skill_id"]) is not None:
            raise ValueError(
                f"skill_id already exists: {data['skill_id']}"
            )

        active_conflicts = self._active_records_by_name(
            manager,
            data["skill_name"],
        )
        conflict_ids = {
            self._record_data(record)["skill_id"]
            for record in active_conflicts
        }
        replacing_id_set = set(replacing_ids)
        unexpected_conflicts = conflict_ids.difference(
            replacing_id_set
        )
        if unexpected_conflicts:
            existing_skill_id = sorted(unexpected_conflicts)[0]
            raise SkillNameAlreadyExistsError(
                data["skill_name"],
                existing_skill_id,
            )

        for replacing_id in replacing_ids:
            replacing_record = self._find_record(
                manager,
                replacing_id,
            )
            if replacing_record is None:
                raise ValueError(
                    f"skill_id was not found: {replacing_id}"
                )
            if (
                self._record_data(replacing_record)["skill_status"]
                != ACTIVE_SKILL_STATUS
            ):
                raise ValueError(
                    f"Skill is not ACTIVE: {replacing_id}"
                )

        stored_status = (
            PENDING_SKILL_STATUS
            if replacing_ids
            else ACTIVE_SKILL_STATUS
        )
        record = MemoryRecord(
            input_text=data["ragmem_q"],
            output_text=data["ragmem_a"],
            source="mcp_skill",
            parent_id=None,
            tag="Green",
            user_keywords=[],
            active_project_name=None,
            embedded_files_snapshot=[],
            retrieval_source_mode="Q",
            direct_recall_key=data["ragmem_recall_key"],
            episode_title=data["ragmem_title"],
            sequence_number=self._next_sequence_number(manager),
            episode_description=data["ragmem_description"],
        )
        record.update_metadata_overlay(
            {
                "skill_id": data["skill_id"],
                "skill_name": data["skill_name"],
                "normalized_skill_name": self._normalize_skill_name(
                    data["skill_name"]
                ),
                "skill_title": data["skill_title"],
                "skill_description": data["skill_description"],
                "skill_status": stored_status,
                "folder_path": data["folder_path"],
                "skill_md_path": data["skill_md_path"],
                "replacing_skill_ids": replacing_ids,
                "notes": list(data["notes"]),
            }
        )

        manager.records.append(record)
        try:
            self._append_record(manager, record)
            manager.save_metainfo()
            manager.refresh_sqlite_index()

            if stored_status == ACTIVE_SKILL_STATUS:
                self._description_vectors.upsert_description(
                    owner_sub=owner,
                    file_id=manager.file_id,
                    record_id=record.record_id,
                    episode_description=data["skill_description"],
                    created_at_utc=record.created_at_utc,
                    skill_id=data["skill_id"],
                    skill_status=stored_status,
                )
        except Exception:
            manager.records = [
                item
                for item in manager.records
                if item.record_id != record.record_id
            ]
            self._rewrite_history(manager)
            manager.save_metainfo()
            manager.refresh_sqlite_index()

            try:
                self._description_vectors.delete_records(
                    [record.record_id]
                )
            except Exception:
                # The vector index is derivative. Preserve the original save
                # failure after durable RagMem/metadata rollback succeeds.
                pass
            raise

        return {
            "file_id": manager.file_id,
            "record_id": record.record_id,
            "recall_key": record.direct_recall_key,
        }

    def finalize_replacement(
        self,
        *,
        owner_sub: str,
        replacement_skill_id: str,
        archived_skills: list[dict[str, Any]],
    ) -> None:
        """Atomically exclude old records and activate one replacement."""
        owner = self._validate_owner_sub(owner_sub)
        replacement_id = self._require_text(
            replacement_skill_id,
            "replacement_skill_id",
        )
        if not isinstance(archived_skills, list) or not archived_skills:
            raise ValueError("archived_skills must be a non-empty list.")

        manager = self._load_manager(owner)
        if manager is None:
            raise ValueError("CLI_SKILL Memory was not found for owner.")
        self._assert_active_name_integrity(manager)

        replacement = self._find_record(manager, replacement_id)
        if replacement is None:
            raise ValueError(
                f"replacement skill_id was not found: {replacement_id}"
            )
        replacement_data = self._record_data(replacement)
        if replacement_data["skill_status"] != PENDING_SKILL_STATUS:
            raise ValueError("Replacement Skill is not PENDING.")

        archived_ids = self._archived_skill_ids(archived_skills)
        expected_ids = replacement_data["replacing_skill_ids"]
        if set(archived_ids) != set(expected_ids):
            raise ValueError(
                "Archived Skill IDs do not match the staged replacement."
            )

        targets = self._validated_archive_targets(
            manager,
            archived_skills,
        )
        snapshots = {
            record.record_id: record.to_index_dict()
            for record, _item in targets
        }
        snapshots[replacement.record_id] = replacement.to_index_dict()

        for record, item in targets:
            record.update_metadata_overlay(
                self._excluded_metadata(item)
            )
        replacement.update_metadata_overlay(
            {
                "skill_status": ACTIVE_SKILL_STATUS,
                "replacing_skill_ids": [],
            }
        )

        try:
            manager.save_metainfo()
            manager.refresh_sqlite_index()
            self._description_vectors.upsert_description(
                owner_sub=owner,
                file_id=manager.file_id,
                record_id=replacement.record_id,
                episode_description=replacement_data[
                    "skill_description"
                ],
                created_at_utc=replacement.created_at_utc,
                skill_id=replacement_id,
                skill_status=ACTIVE_SKILL_STATUS,
            )
        except Exception:
            try:
                self._restore_metadata_snapshots(
                    manager,
                    snapshots,
                )
                manager.save_metainfo()
                manager.refresh_sqlite_index()
                self._description_vectors.delete_records(
                    [replacement.record_id]
                )
            except Exception as rollback_error:
                raise SkillRegistryIntegrityError(
                    "Replacement Memory rollback failed."
                ) from rollback_error
            raise

    def delete_skill(
        self,
        *,
        owner_sub: str,
        skill_id: str,
    ) -> None:
        """Delete one staged replacement during workflow rollback."""
        owner = self._validate_owner_sub(owner_sub)
        clean_skill_id = self._require_text(skill_id, "skill_id")
        manager = self._load_manager(owner)
        if manager is None:
            raise ValueError("CLI_SKILL Memory was not found for owner.")

        record = self._find_record(manager, clean_skill_id)
        if record is None:
            raise ValueError(f"skill_id was not found: {clean_skill_id}")
        if self._record_data(record)["skill_status"] != PENDING_SKILL_STATUS:
            raise ValueError("Only a PENDING Skill may be rolled back.")

        original_records = list(manager.records)
        manager.records = [
            item
            for item in manager.records
            if item.record_id != record.record_id
        ]
        try:
            self._rewrite_history(manager)
            manager.save_metainfo()
            manager.refresh_sqlite_index()
            self._description_vectors.delete_records([record.record_id])
        except Exception:
            try:
                manager.records = original_records
                self._rewrite_history(manager)
                manager.save_metainfo()
                manager.refresh_sqlite_index()
            except Exception as rollback_error:
                raise SkillRegistryIntegrityError(
                    "Staged Skill deletion rollback failed."
                ) from rollback_error
            raise

    def search_skills(
        self,
        *,
        owner_sub: str,
        query: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        """Return ACTIVE owner Skill descriptions ranked by cosine."""
        owner = self._validate_owner_sub(owner_sub)
        clean_query = self._require_text(query, "query")

        if (
            not isinstance(limit, int)
            or isinstance(limit, bool)
            or limit < 1
        ):
            raise ValueError("limit must be a positive integer.")

        manager = self._load_manager(owner)
        if manager is None:
            return []
        self._assert_active_name_integrity(manager)

        active_records = {
            record.record_id: record
            for record in manager.records
            if str(
                record.to_index_dict().get("skill_status", "")
            ).upper()
            == ACTIVE_SKILL_STATUS
        }
        if not active_records:
            return []

        hits = self._description_vectors.search_descriptions(
            owner_sub=owner,
            query_description=clean_query,
            candidate_record_ids=list(active_records),
            limit=limit,
        )

        candidates: list[dict[str, Any]] = []
        for hit in hits:
            record = active_records.get(
                str(hit.get("record_id", ""))
            )
            if record is None:
                continue

            metadata = record.to_index_dict()
            candidates.append(
                {
                    "skill_id": str(
                        metadata.get("skill_id", "")
                    ),
                    "skill_title": self._skill_title(
                        record,
                        metadata,
                    ),
                    "skill_description": self._skill_description(
                        record,
                        metadata,
                    ),
                    "skill_status": str(
                        metadata.get("skill_status", "")
                    ),
                    "cosine_similarity": hit.get(
                        "cosine_similarity"
                    ),
                }
            )

        return candidates

    def get_skill(
        self,
        *,
        owner_sub: str,
        skill_id: str,
        active_only: bool = False,
    ) -> dict[str, Any] | None:
        """Return one owner-scoped Skill by exact Skill ID."""
        owner = self._validate_owner_sub(owner_sub)
        clean_skill_id = self._require_text(
            skill_id,
            "skill_id",
        )
        manager = self._load_manager(owner)
        if manager is None:
            return None
        self._assert_active_name_integrity(manager)

        record = self._find_record(manager, clean_skill_id)
        if record is None:
            return None

        data = self._record_data(record)
        if (
            active_only
            and data["skill_status"] != ACTIVE_SKILL_STATUS
        ):
            return None

        return data

    def exclude_skills(
        self,
        *,
        owner_sub: str,
        archived_skills: list[dict[str, Any]],
    ) -> None:
        """Preserve episodes while changing state to EXCLUDED."""
        owner = self._validate_owner_sub(owner_sub)

        if not isinstance(archived_skills, list):
            raise ValueError("archived_skills must be a list.")
        if not archived_skills:
            return

        manager = self._load_manager(owner)
        if manager is None:
            raise ValueError(
                "CLI_SKILL Memory was not found for owner."
            )

        self._assert_active_name_integrity(manager)
        targets = self._validated_archive_targets(
            manager,
            archived_skills,
        )
        snapshots = {
            record.record_id: record.to_index_dict()
            for record, _item in targets
        }

        for record, item in targets:
            record.update_metadata_overlay(
                self._excluded_metadata(item)
            )

        try:
            manager.save_metainfo()
            manager.refresh_sqlite_index()
        except Exception:
            try:
                self._restore_metadata_snapshots(
                    manager,
                    snapshots,
                )
                manager.save_metainfo()
                manager.refresh_sqlite_index()
            except Exception as rollback_error:
                raise SkillRegistryIntegrityError(
                    "Skill exclusion rollback failed."
                ) from rollback_error
            raise

        # Chroma is derivative. Retrieval first builds its allowed Record-ID
        # scope from this updated RagMeta truth, so EXCLUDED records are never
        # queried even if their old description vector remains physically.

    def _load_or_create_manager(
        self,
        owner_sub: str,
    ) -> MemoryManager:
        manager = self._load_manager(owner_sub)
        if manager is not None:
            return manager

        return self._create_manager(owner_sub)

    def _load_manager(
        self,
        owner_sub: str,
    ) -> MemoryManager | None:
        meta_path = self._fixed_meta_path(owner_sub)
        ragmem_path = self._fixed_ragmem_path(owner_sub)

        if not meta_path.exists() and not ragmem_path.exists():
            return None
        if not meta_path.is_file() or not ragmem_path.is_file():
            raise ValueError(
                "CLI_SKILL RagMem and RagMeta are inconsistent."
            )

        try:
            metadata = json.loads(
                meta_path.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError(
                "CLI_SKILL RagMeta cannot be read."
            ) from error

        if not isinstance(metadata, dict):
            raise ValueError(
                "CLI_SKILL RagMeta must contain an object."
            )
        if str(metadata.get("owner_sub", "")) != owner_sub:
            raise ValueError(
                "CLI_SKILL RagMeta owner does not match."
            )

        file_id = self._require_text(
            metadata.get("file_id"),
            "file_id",
        )
        manager = self._new_manager()
        manager.load_history(file_id)

        if manager.owner_sub != owner_sub:
            raise ValueError(
                "CLI_SKILL SQLite owner does not match."
            )

        return manager

    def _create_manager(self, owner_sub: str) -> MemoryManager:
        manager = self._new_manager()
        storage_folder = f"{owner_sub}/cli_knowledge"

        manager.start_new_history(
            CLI_SKILL_TITLE,
            memory_type=CLI_SKILL_MEMORY_TYPE,
            memory_description=CLI_SKILL_DESCRIPTION,
            owner_sub=owner_sub,
            storage_folder=storage_folder,
        )

        # CLI knowledge is a singleton and therefore uses fixed filenames.
        manager.filename_ragmem = (
            f"{storage_folder}/CLI_SKILL.ragmem"
        )
        manager.filename_meta = (
            f"{storage_folder}/CLI_SKILL.ragmeta.json"
        )
        manager.ragmem_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        manager.ragmem_path.touch(exist_ok=False)
        manager.save_metainfo()
        manager.refresh_sqlite_index()

        return manager

    def _new_manager(self) -> MemoryManager:
        return MemoryManager(
            memory_root=self.memory_root,
            sqlite_path=self.sqlite_path,
        )

    def _fixed_ragmem_path(self, owner_sub: str) -> Path:
        return (
            self.memory_root
            / "files"
            / owner_sub
            / "cli_knowledge"
            / "CLI_SKILL.ragmem"
        )

    def _fixed_meta_path(self, owner_sub: str) -> Path:
        return (
            self.memory_root
            / "files"
            / owner_sub
            / "cli_knowledge"
            / "CLI_SKILL.ragmeta.json"
        )

    @staticmethod
    def _append_record(
        manager: MemoryManager,
        record: MemoryRecord,
    ) -> None:
        with manager.ragmem_path.open(
            "a",
            encoding="utf-8",
        ) as file:
            file.write(record.to_ragmem_block())
            file.write("\n")

    @staticmethod
    def _rewrite_history(manager: MemoryManager) -> None:
        temporary_path = manager.ragmem_path.with_suffix(
            ".ragmem.tmp"
        )

        with temporary_path.open(
            "w",
            encoding="utf-8",
        ) as file:
            for record in manager.records:
                file.write(record.to_ragmem_block())
                file.write("\n")

        temporary_path.replace(manager.ragmem_path)

    @staticmethod
    def _next_sequence_number(
        manager: MemoryManager,
    ) -> int:
        return max(
            len(manager.records),
            max(
                (
                    record.sequence_number
                    for record in manager.records
                ),
                default=0,
            ),
        ) + 1

    @staticmethod
    def _find_record(
        manager: MemoryManager,
        skill_id: str,
    ) -> MemoryRecord | None:
        for record in manager.records:
            metadata = record.to_index_dict()
            if str(metadata.get("skill_id", "")) == skill_id:
                return record

        return None

    @classmethod
    def _active_records_by_name(
        cls,
        manager: MemoryManager,
        skill_name: str,
    ) -> list[MemoryRecord]:
        normalized_name = cls._normalize_skill_name(skill_name)
        matches: list[MemoryRecord] = []
        for record in manager.records:
            data = cls._record_data(record)
            if data["skill_status"] != ACTIVE_SKILL_STATUS:
                continue
            if data["normalized_skill_name"] == normalized_name:
                matches.append(record)
        return matches

    @classmethod
    def _assert_active_name_integrity(
        cls,
        manager: MemoryManager,
    ) -> None:
        active_ids_by_name: dict[str, list[str]] = {}
        for record in manager.records:
            data = cls._record_data(record)
            if data["skill_status"] != ACTIVE_SKILL_STATUS:
                continue
            normalized_name = data["normalized_skill_name"]
            active_ids_by_name.setdefault(normalized_name, []).append(
                data["skill_id"]
            )

        duplicates = {
            name: ids
            for name, ids in active_ids_by_name.items()
            if name and len(ids) > 1
        }
        if duplicates:
            details = "; ".join(
                f"{name}: {', '.join(sorted(ids))}"
                for name, ids in sorted(duplicates.items())
            )
            raise SkillRegistryIntegrityError(
                "Duplicate ACTIVE normalized skill_name values: "
                + details
            )

    @classmethod
    def _validated_archive_targets(
        cls,
        manager: MemoryManager,
        archived_skills: list[dict[str, Any]],
    ) -> list[tuple[MemoryRecord, dict[str, Any]]]:
        targets: list[tuple[MemoryRecord, dict[str, Any]]] = []
        seen_ids: set[str] = set()
        for item in archived_skills:
            if not isinstance(item, dict):
                raise ValueError("Each archived Skill must be an object.")

            skill_id = cls._require_text(
                item.get("skill_id"),
                "skill_id",
            )
            if skill_id in seen_ids:
                raise ValueError(
                    f"Duplicate archived skill_id: {skill_id}"
                )
            seen_ids.add(skill_id)

            record = cls._find_record(manager, skill_id)
            if record is None:
                raise ValueError(f"skill_id was not found: {skill_id}")
            if (
                cls._record_data(record)["skill_status"]
                != ACTIVE_SKILL_STATUS
            ):
                raise ValueError(f"Skill is not ACTIVE: {skill_id}")

            cls._excluded_metadata(item)
            targets.append((record, item))

        return targets

    @classmethod
    def _archived_skill_ids(
        cls,
        archived_skills: list[dict[str, Any]],
    ) -> list[str]:
        return [
            cls._require_text(item.get("skill_id"), "skill_id")
            for item in archived_skills
        ]

    @classmethod
    def _excluded_metadata(
        cls,
        item: dict[str, Any],
    ) -> dict[str, Any]:
        notes = item.get("notes", [])
        if not isinstance(notes, list):
            raise ValueError("notes must be a list.")

        return {
            "skill_status": EXCLUDED_SKILL_STATUS,
            "folder_path": cls._require_text(
                item.get("folder_path"),
                "folder_path",
            ),
            "skill_md_path": cls._require_text(
                item.get("skill_md_path"),
                "skill_md_path",
            ),
            "notes": list(notes),
        }

    @staticmethod
    def _restore_metadata_snapshots(
        manager: MemoryManager,
        snapshots: dict[str, dict[str, Any]],
    ) -> None:
        for record in manager.records:
            snapshot = snapshots.get(record.record_id)
            if snapshot is not None:
                record.update_metadata_overlay(snapshot)

    @staticmethod
    def _skill_title(
        record: MemoryRecord,
        metadata: dict[str, Any],
    ) -> str:
        return str(
            metadata.get("skill_title")
            or record.episode_title
            or metadata.get("skill_name")
            or ""
        ).strip()

    @staticmethod
    def _skill_description(
        record: MemoryRecord,
        metadata: dict[str, Any],
    ) -> str:
        return str(
            metadata.get("skill_description")
            or record.episode_description
            or ""
        ).strip()

    @staticmethod
    def _record_data(
        record: MemoryRecord,
    ) -> dict[str, Any]:
        metadata = record.to_index_dict()

        notes_value = metadata.get("notes", [])
        notes = (
            list(notes_value)
            if isinstance(notes_value, list)
            else []
        )
        replacing_ids_value = metadata.get(
            "replacing_skill_ids",
            [],
        )
        replacing_ids = (
            list(replacing_ids_value)
            if isinstance(replacing_ids_value, list)
            else []
        )

        return {
            "skill_id": str(metadata.get("skill_id", "")),
            "skill_name": str(metadata.get("skill_name", "")),
            "normalized_skill_name": str(
                metadata.get("normalized_skill_name")
                or McpSkillMemoryStore._normalize_skill_name(
                    str(metadata.get("skill_name", ""))
                )
            ),
            "skill_title": McpSkillMemoryStore._skill_title(
                record,
                metadata,
            ),
            "skill_status": str(
                metadata.get("skill_status", "")
            ).upper(),
            "skill_description": (
                McpSkillMemoryStore._skill_description(
                    record,
                    metadata,
                )
            ),
            "folder_path": str(
                metadata.get("folder_path", "")
            ),
            "skill_md_path": str(
                metadata.get("skill_md_path", "")
            ),
            "notes": notes,
            "ragmem_record_id": record.record_id,
            "ragmem_recall_key": record.direct_recall_key,
            "ragmem_title": record.episode_title,
            "ragmem_description": record.episode_description,
            "replacing_skill_ids": replacing_ids,
        }

    @staticmethod
    def _validated_skill_data(
        skill_data: dict[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(skill_data, dict):
            raise ValueError(
                "skill_data must be a dictionary."
            )

        required_fields = (
            "skill_id",
            "skill_name",
            "skill_title",
            "skill_description",
            "folder_path",
            "skill_md_path",
            "ragmem_recall_key",
            "ragmem_title",
            "ragmem_description",
            "ragmem_q",
            "ragmem_a",
            "skill_status",
        )

        cleaned = dict(skill_data)
        for field_name in required_fields:
            cleaned[field_name] = (
                McpSkillMemoryStore._require_text(
                    skill_data.get(field_name),
                    field_name,
                )
            )

        skill_id = cleaned["skill_id"]
        if (
            skill_id in {".", ".."}
            or _SAFE_OWNER_SUB.fullmatch(skill_id) is None
        ):
            raise ValueError(
                "skill_id contains unsafe characters."
            )

        if (
            cleaned["skill_status"].upper()
            != ACTIVE_SKILL_STATUS
        ):
            raise ValueError(
                "A new persisted Skill must be ACTIVE."
            )
        cleaned["skill_status"] = ACTIVE_SKILL_STATUS

        notes = skill_data.get("notes", [])
        if not isinstance(notes, list):
            raise ValueError("notes must be a list.")

        cleaned["notes"] = list(notes)
        return cleaned

    @staticmethod
    def _validate_owner_sub(owner_sub: str) -> str:
        owner = McpSkillMemoryStore._require_text(
            owner_sub,
            "owner_sub",
        )
        if (
            owner in {".", ".."}
            or _SAFE_OWNER_SUB.fullmatch(owner) is None
        ):
            raise ValueError(
                "owner_sub contains unsafe characters."
            )

        return owner

    @staticmethod
    def _clean_skill_ids(skill_ids: list[str]) -> list[str]:
        if not isinstance(skill_ids, list):
            raise ValueError("replacing_skill_ids must be a list.")

        cleaned: list[str] = []
        seen: set[str] = set()
        for skill_id in skill_ids:
            value = McpSkillMemoryStore._require_text(
                skill_id,
                "replacing_skill_id",
            )
            if (
                value in {".", ".."}
                or _SAFE_OWNER_SUB.fullmatch(value) is None
            ):
                raise ValueError(
                    "replacing_skill_id contains unsafe characters."
                )
            if value not in seen:
                cleaned.append(value)
                seen.add(value)

        return cleaned

    @staticmethod
    def _normalize_skill_name(skill_name: str) -> str:
        return McpSkillMemoryStore._require_text(
            skill_name,
            "skill_name",
        ).casefold()

    @staticmethod
    def _require_text(
        value: Any,
        field_name: str,
    ) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(
                f"{field_name} must not be empty."
            )

        return value.strip()