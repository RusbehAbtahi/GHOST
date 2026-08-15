"""Index and search MCP Episode Descriptions with cosine similarity.

This module owns only the derivative Chroma index used by intelligent MCP
Episodic Recall. Durable episode bodies, metadata, owner authorization, date
filtering, and exact record loading remain responsibilities of McpMemoryStore.

Main classes:
    McpEpisodicDescriptionVectorStore:
        Owns one lazy-loaded Chroma collection of Episode Description vectors.

Main methods:
    upsert_description():
        Embeds and replaces one episode's stored description vector.
    search_descriptions():
        Returns cosine-ranked hits within one owner and candidate-ID scope.
    delete_records():
        Removes derivative vectors for deleted memory episodes.

Important notes:
    The OpenAI embedder and Chroma collection are initialized on first use so
    constructing the MCP application does not make a network call.
"""

from __future__ import annotations

import threading

from pathlib import Path
from typing import Any

DEFAULT_COLLECTION_NAME = "mcp_episodic_descriptions_v1"
DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"


class McpEpisodicDescriptionVectorStore:
    """Own the derivative vector index for MCP Episode Descriptions."""

    def __init__(
        self,
        persist_dir: str | Path,
        *,
        collection_name: str = DEFAULT_COLLECTION_NAME,
        embedding_model: str = DEFAULT_EMBEDDING_MODEL,
        embedder: Any | None = None,
    ) -> None:
        """Store configuration and defer external-client initialization."""
        self.persist_dir = Path(persist_dir)
        self.collection_name = str(collection_name).strip()
        self.embedding_model = str(embedding_model).strip()
        if not self.collection_name:
            raise ValueError("collection_name must not be empty.")
        if not self.embedding_model:
            raise ValueError("embedding_model must not be empty.")

        self._embedder = embedder
        self._client: Any | None = None
        self._collection: Any | None = None
        self._lock = threading.RLock()

        self.persist_dir.mkdir(parents=True, exist_ok=True)

    def upsert_description(
        self,
        *,
        owner_sub: str,
        file_id: str,
        record_id: str,
        episode_description: str,
        created_at_utc: str,
    ) -> None:
        """Embed and persist one description under its stable Record ID."""
        owner = self._require_text(owner_sub, "owner_sub")
        memory_file_id = self._require_text(file_id, "file_id")
        memory_record_id = self._require_text(record_id, "record_id")
        description = self._require_text(
            episode_description,
            "episode_description",
        )
        created_at = self._require_text(created_at_utc, "created_at_utc")

        with self._lock:
            collection = self._get_collection()
            embedding = self._embed_one(description)
            collection.upsert(
                ids=[memory_record_id],
                documents=[description],
                embeddings=[embedding],
                metadatas=[
                    {
                        "owner_sub": owner,
                        "file_id": memory_file_id,
                        "record_id": memory_record_id,
                        "created_at_utc": created_at,
                    }
                ],
            )

    def search_descriptions(
        self,
        *,
        owner_sub: str,
        query_description: str,
        candidate_record_ids: list[str],
        limit: int,
    ) -> list[dict[str, Any]]:
        """Return cosine-ranked description hits from the allowed records."""
        owner = self._require_text(owner_sub, "owner_sub")
        query = self._require_text(query_description, "query_description")
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
            raise ValueError("limit must be a positive integer.")

        allowed_ids = self._clean_record_ids(candidate_record_ids)
        if not allowed_ids:
            return []

        with self._lock:
            collection = self._get_collection()
            query_embedding = self._embed_one(query)
            result = collection.query(
                query_embeddings=[query_embedding],
                n_results=min(limit, len(allowed_ids)),
                where={
                    "$and": [
                        {"owner_sub": owner},
                        {"record_id": {"$in": allowed_ids}},
                    ]
                },
                include=["documents", "metadatas", "distances"],
            )

        return self._normalize_query_result(result)

    def delete_records(self, record_ids: list[str] | set[str]) -> None:
        """Delete vectors by stable Record ID; an empty request is a no-op."""
        clean_ids = self._clean_record_ids(list(record_ids))
        if not clean_ids:
            return

        with self._lock:
            self._get_collection().delete(ids=clean_ids)

    def _get_collection(self) -> Any:
        if self._collection is not None:
            return self._collection

        import chromadb

        self._client = chromadb.PersistentClient(path=str(self.persist_dir))
        self._collection = self._client.get_or_create_collection(
            name=self.collection_name,
            metadata={"hnsw:space": "cosine"},
        )
        return self._collection

    def _embed_one(self, text: str) -> list[float]:
        if self._embedder is None:
            from ragstream.ingestion.embedder import Embedder

            self._embedder = Embedder(model=self.embedding_model)

        embeddings = self._embedder.embed([text])
        if not isinstance(embeddings, list) or len(embeddings) != 1:
            raise ValueError("embedding provider returned an invalid result.")

        embedding = embeddings[0]
        if not isinstance(embedding, list) or not embedding:
            raise ValueError("embedding provider returned an empty vector.")
        return [float(value) for value in embedding]

    @staticmethod
    def _normalize_query_result(result: Any) -> list[dict[str, Any]]:
        if not isinstance(result, dict):
            return []

        ids = McpEpisodicDescriptionVectorStore._first_result_list(
            result.get("ids")
        )
        documents = McpEpisodicDescriptionVectorStore._first_result_list(
            result.get("documents")
        )
        metadatas = McpEpisodicDescriptionVectorStore._first_result_list(
            result.get("metadatas")
        )
        distances = McpEpisodicDescriptionVectorStore._first_result_list(
            result.get("distances")
        )

        hits: list[dict[str, Any]] = []
        for index, vector_id in enumerate(ids):
            distance_value = (
                distances[index] if index < len(distances) else None
            )
            distance = (
                float(distance_value)
                if distance_value is not None
                else None
            )
            metadata_value = (
                metadatas[index] if index < len(metadatas) else {}
            )
            metadata = (
                dict(metadata_value)
                if isinstance(metadata_value, dict)
                else {}
            )
            document = documents[index] if index < len(documents) else ""

            hits.append(
                {
                    "record_id": str(
                        metadata.get("record_id") or vector_id
                    ),
                    "episode_description": str(document or ""),
                    "cosine_distance": distance,
                    "cosine_similarity": (
                        1.0 - distance if distance is not None else None
                    ),
                }
            )
        return hits

    @staticmethod
    def _first_result_list(value: Any) -> list[Any]:
        if not isinstance(value, list) or not value:
            return []
        first = value[0]
        return list(first) if isinstance(first, list) else []

    @staticmethod
    def _clean_record_ids(record_ids: list[str]) -> list[str]:
        cleaned: list[str] = []
        seen: set[str] = set()
        for record_id in record_ids:
            value = str(record_id or "").strip()
            if value and value not in seen:
                cleaned.append(value)
                seen.add(value)
        return cleaned

    @staticmethod
    def _require_text(value: str, field_name: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field_name} must not be empty.")
        return value.strip()