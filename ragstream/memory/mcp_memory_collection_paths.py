"""Define safe physical folder paths for GHOST Collection Memory.

This module owns only Collection folder naming and owner-relative path
construction. Collection persistence, browsing, and management stay elsewhere.

Main functions:
    normalize_collection_folder():
        Validates one folder name and maps empty input to Main.
    collection_storage_folder():
        Builds the owner-scoped relative Collection storage path.
"""

from __future__ import annotations

from pathlib import Path


COLLECTION_MAIN_FOLDER = "Main"
COLLECTION_ARCHIVE_FOLDER = "Archive"


def normalize_collection_folder(folder: str | None) -> str:
    """Return one safe Collection folder name, mapping empty input to Main."""
    value = str(folder or "").strip().replace("\\", "/")
    if not value or value.casefold() == COLLECTION_MAIN_FOLDER.casefold():
        return COLLECTION_MAIN_FOLDER

    path = Path(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("folder must be a safe relative Collection folder")

    clean = "/".join(path.parts)
    if clean.casefold() == COLLECTION_ARCHIVE_FOLDER.casefold():
        return COLLECTION_ARCHIVE_FOLDER
    if any(
        part.casefold() == COLLECTION_ARCHIVE_FOLDER.casefold()
        for part in path.parts
    ):
        raise ValueError("Archive is reserved as a top-level Collection folder")
    return clean


def collection_storage_folder(owner_sub: str, folder: str | None = None) -> str:
    """Build the owner-scoped relative storage folder for one Collection."""
    clean_folder = normalize_collection_folder(folder)
    root = f"{owner_sub}/collections"
    if clean_folder == COLLECTION_MAIN_FOLDER:
        return root
    return f"{root}/{clean_folder}"
