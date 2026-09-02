"""Resolve one GHOST RagMem into the standard Memory retrieval backend.

Main classes:
    ResolvedRagMem:
        Carries the validated manager, vector store, and index location.
    RagMemResolver:
        Validates artifacts, repairs their SQLite mirror, and fills missing
        standard body vectors.

Main methods:
    resolve():
        Prepares one owner-compatible .ragmem and .ragmeta.json pair.

Important notes:
    RagMem and RagMeta remain authoritative. SQLite and Chroma are derivative
    indexes and are repaired only for the selected memory.
"""

from __future__ import annotations

import json
import re
import sqlite3

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


MEMORY_VECTOR_COLLECTION = "memory_vectors"
_WSL_UNC_PREFIX = re.compile(
    r"^(?:\\\\|\\|//)wsl\.localhost(?:\\|/)[^\\/]+(?:\\|/)",
    re.IGNORECASE,
)
_WSL_HOST_PREFIX = re.compile(
    r"^(?:\\\\|\\|//)?wsl\.localhost",
    re.IGNORECASE,
)


class RagMemResolutionError(RuntimeError):
    """Report a specific artifact or derivative-index preparation failure."""


@dataclass(frozen=True, slots=True)
class ResolvedRagMem:
    """Hold the retrieval objects prepared for one selected RagMem."""

    ragmem_path: Path
    meta_path: Path
    sqlite_path: Path
    memory_manager: Any
    memory_vector_store: Any
    vectors_created: int


class RagMemResolver:
    """Prepare one explicit GHOST RagMem without scanning unrelated stores."""

    def __init__(
        self,
        *,
        embedder_factory: Callable[[], Any] | None = None,
    ) -> None:
        self._embedder_factory = (
            embedder_factory or self._create_embedder
        )

    def resolve(
        self,
        *,
        ragmem_path: str,
        owner_sub: str,
    ) -> ResolvedRagMem:
        """Validate artifacts and ensure their standard retrieval indexes."""
        path = self._resolve_path(ragmem_path)
        meta_path = path.with_suffix(".ragmeta.json")
        metadata = self._read_metadata(meta_path)
        owner = str(owner_sub or "").strip()
        self._validate_owner(metadata, owner)

        memory_root = self._memory_root(path)
        files_root = memory_root / "files"
        relative_ragmem = path.relative_to(files_root).as_posix()
        relative_meta = meta_path.relative_to(files_root).as_posix()
        self._validate_declared_paths(
            metadata,
            relative_ragmem=relative_ragmem,
            relative_meta=relative_meta,
        )

        sqlite_path = memory_root / "memory_index.sqlite3"
        manager = self._load_manager(
            memory_root=memory_root,
            sqlite_path=sqlite_path,
            metadata=metadata,
            relative_ragmem=relative_ragmem,
            relative_meta=relative_meta,
        )
        if manager.ragmem_path.resolve() != path:
            raise RagMemResolutionError(
                "RagMem path does not match its metadata file_id"
            )
        if manager.owner_sub and manager.owner_sub != owner:
            raise RagMemResolutionError(
                "RagMem does not belong to the authenticated owner"
            )

        vector_store = self._create_vector_store(memory_root)
        vectors_created = self._ingest_missing_records(
            manager,
            vector_store,
        )
        return ResolvedRagMem(
            ragmem_path=path,
            meta_path=meta_path,
            sqlite_path=sqlite_path,
            memory_manager=manager,
            memory_vector_store=vector_store,
            vectors_created=vectors_created,
        )

    @staticmethod
    def _resolve_path(value: str) -> Path:
        text = str(value or "").strip()
        if not text:
            raise RagMemResolutionError(
                "memory_retrieval requires a RagMem path"
            )

        normalized = text
        if _WSL_UNC_PREFIX.match(text):
            normalized = "/" + _WSL_UNC_PREFIX.sub("", text)
            normalized = normalized.replace("\\", "/")
        elif _WSL_HOST_PREFIX.match(text):
            raise RagMemResolutionError(
                "Malformed WSL path: expected "
                r"\\wsl.localhost\<distro>\path\file.ragmem"
            )

        path = Path(normalized).expanduser().resolve()
        if path.suffix.lower() != ".ragmem" or not path.is_file():
            raise RagMemResolutionError(
                "RagMem path must reference an existing .ragmem file"
            )
        return path

    @staticmethod
    def _read_metadata(meta_path: Path) -> dict[str, Any]:
        if not meta_path.is_file():
            raise RagMemResolutionError(
                "RagMem metadata sidecar is missing"
            )
        try:
            metadata = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise RagMemResolutionError(
                "RagMem metadata sidecar is unreadable"
            ) from error
        if not isinstance(metadata, dict):
            raise RagMemResolutionError(
                "RagMem metadata sidecar must contain an object"
            )
        if not str(metadata.get("file_id", "") or "").strip():
            raise RagMemResolutionError(
                "RagMem metadata has no file_id"
            )
        return metadata

    @staticmethod
    def _validate_owner(
        metadata: dict[str, Any],
        owner_sub: str,
    ) -> None:
        if not owner_sub:
            raise RagMemResolutionError(
                "authenticated owner is required"
            )
        stored_owner = str(
            metadata.get("owner_sub", "") or ""
        ).strip()
        if stored_owner and stored_owner != owner_sub:
            raise RagMemResolutionError(
                "RagMem does not belong to the authenticated owner"
            )

    @staticmethod
    def _memory_root(path: Path) -> Path:
        for parent in path.parents:
            if parent.name == "files":
                return parent.parent
        raise RagMemResolutionError(
            "RagMem path is not inside a GHOST memory/files root"
        )

    @staticmethod
    def _validate_declared_paths(
        metadata: dict[str, Any],
        *,
        relative_ragmem: str,
        relative_meta: str,
    ) -> None:
        declared_ragmem = str(
            metadata.get("filename_ragmem", "") or ""
        ).replace("\\", "/")
        declared_meta = str(
            metadata.get("filename_meta", "") or ""
        ).replace("\\", "/")
        if declared_ragmem and declared_ragmem != relative_ragmem:
            raise RagMemResolutionError(
                "RagMem path does not match filename_ragmem metadata"
            )
        if declared_meta and declared_meta != relative_meta:
            raise RagMemResolutionError(
                "RagMem sidecar path does not match filename_meta metadata"
            )

    def _load_manager(
        self,
        *,
        memory_root: Path,
        sqlite_path: Path,
        metadata: dict[str, Any],
        relative_ragmem: str,
        relative_meta: str,
    ) -> Any:
        from ragstream.memory.memory_manager import MemoryManager

        manager = MemoryManager(
            memory_root=memory_root,
            sqlite_path=sqlite_path,
        )
        self._register_file(
            sqlite_path=sqlite_path,
            metadata=metadata,
            relative_ragmem=relative_ragmem,
            relative_meta=relative_meta,
        )
        try:
            manager.load_history(str(metadata["file_id"]))
        except (OSError, ValueError, json.JSONDecodeError) as error:
            raise RagMemResolutionError(
                "RagMem body or metadata could not be loaded"
            ) from error

        expected_count = metadata.get("record_count")
        if expected_count is not None:
            try:
                expected = int(expected_count)
            except (TypeError, ValueError) as error:
                raise RagMemResolutionError(
                    "RagMem metadata record_count is invalid"
                ) from error
            if expected != len(manager.records):
                raise RagMemResolutionError(
                    "RagMem body record count does not match its metadata"
                )
        return manager

    @staticmethod
    def _register_file(
        *,
        sqlite_path: Path,
        metadata: dict[str, Any],
        relative_ragmem: str,
        relative_meta: str,
    ) -> None:
        actors = metadata.get("actors", [])
        if not isinstance(actors, list):
            actors = []
        created_at = str(
            metadata.get("created_at_utc", "") or ""
        )
        updated_at = str(
            metadata.get("updated_at_utc", "") or created_at
        )
        with sqlite3.connect(sqlite_path) as connection:
            connection.execute(
                """
                INSERT INTO memory_files (
                    file_id, title, memory_type, memory_description,
                    actors_json, filename_ragmem, filename_meta,
                    created_at_utc, updated_at_utc, record_count,
                    owner_sub, expires_at_utc
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(file_id) DO UPDATE SET
                    title = excluded.title,
                    memory_type = excluded.memory_type,
                    memory_description = excluded.memory_description,
                    actors_json = excluded.actors_json,
                    filename_ragmem = excluded.filename_ragmem,
                    filename_meta = excluded.filename_meta,
                    created_at_utc = excluded.created_at_utc,
                    updated_at_utc = excluded.updated_at_utc,
                    record_count = excluded.record_count,
                    owner_sub = excluded.owner_sub,
                    expires_at_utc = excluded.expires_at_utc
                """,
                (
                    str(metadata["file_id"]),
                    str(metadata.get("title", "") or "Untitled"),
                    str(metadata.get("memory_type", "") or ""),
                    str(metadata.get("memory_description", "") or ""),
                    json.dumps(actors, ensure_ascii=False),
                    relative_ragmem,
                    relative_meta,
                    created_at,
                    updated_at,
                    int(metadata.get("record_count", 0) or 0),
                    str(metadata.get("owner_sub", "") or ""),
                    metadata.get("expires_at_utc"),
                ),
            )
            connection.commit()

    def _create_vector_store(self, memory_root: Path) -> Any:
        from ragstream.memory.ingestion.memory_vector_store import (
            MemoryVectorStore,
        )

        return MemoryVectorStore(
            persist_dir=str(memory_root / "vector_db"),
            collection_name=MEMORY_VECTOR_COLLECTION,
            embedder=self._embedder_factory(),
        )

    @staticmethod
    def _ingest_missing_records(
        manager: Any,
        vector_store: Any,
    ) -> int:
        missing_ids = [
            str(record.record_id)
            for record in manager.records
            if vector_store.count_record(str(record.record_id)) == 0
        ]
        if not missing_ids:
            return 0

        from ragstream.memory.ingestion.memory_chunker import MemoryChunker
        from ragstream.memory.ingestion.memory_ingestion_manager import (
            MemoryIngestionManager,
        )

        ingestion = MemoryIngestionManager(
            memory_manager=manager,
            memory_chunker=MemoryChunker(),
            memory_vector_store=vector_store,
        )
        for record_id in missing_ids:
            result = ingestion.ingest_record(record_id)
            if not result.get("success"):
                message = str(
                    result.get("message", "unknown ingestion failure")
                )
                raise RagMemResolutionError(
                    f"memory vector creation failed for {record_id}: {message}"
                )
        return len(missing_ids)

    @staticmethod
    def _create_embedder() -> Any:
        from ragstream.ingestion.embedder import Embedder

        try:
            return Embedder(model="text-embedding-3-large")
        except (OSError, ValueError) as error:
            raise RagMemResolutionError(
                f"memory embedder initialization failed: {error}"
            ) from error
