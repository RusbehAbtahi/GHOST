"""Tests for explicit GHOST RagMem path resolution."""

from __future__ import annotations

import pytest

from ragstream.mcp.ragmem_resolver import (
    RagMemResolutionError,
    RagMemResolver,
)


def test_wsl_unc_path_resolves_to_existing_linux_ragmem(tmp_path) -> None:
    ragmem = tmp_path / "memory.ragmem"
    ragmem.write_text("body", encoding="utf-8")
    unc_path = (
        r"\\wsl.localhost\Ubuntu-24.04"
        + str(ragmem).replace("/", "\\")
    )

    resolved = RagMemResolver._resolve_path(unc_path)

    assert resolved == ragmem.resolve()


def test_single_leading_backslash_wsl_path_is_normalized(tmp_path) -> None:
    ragmem = tmp_path / "memory.ragmem"
    ragmem.write_text("body", encoding="utf-8")
    wsl_path = (
        r"\wsl.localhost\Ubuntu-24.04"
        + str(ragmem).replace("/", "\\")
    )

    resolved = RagMemResolver._resolve_path(wsl_path)

    assert resolved == ragmem.resolve()


def test_malformed_wsl_path_reports_path_format_error() -> None:
    with pytest.raises(RagMemResolutionError, match="Malformed WSL path"):
        RagMemResolver._resolve_path(r"\wsl.localhost")


def test_nonexistent_ragmem_still_reports_existing_file_error(tmp_path) -> None:
    missing = tmp_path / "missing.ragmem"

    with pytest.raises(
        RagMemResolutionError,
        match=r"existing \.ragmem file",
    ):
        RagMemResolver._resolve_path(str(missing))


def test_resolve_requires_matching_metadata_sidecar(tmp_path) -> None:
    ragmem = tmp_path / "memory.ragmem"
    ragmem.write_text("body", encoding="utf-8")

    with pytest.raises(RagMemResolutionError, match="sidecar is missing"):
        RagMemResolver(embedder_factory=object).resolve(
            ragmem_path=str(ragmem),
            owner_sub="owner",
        )


def test_metadata_owner_mismatch_is_rejected() -> None:
    with pytest.raises(RagMemResolutionError, match="authenticated owner"):
        RagMemResolver._validate_owner(
            {"owner_sub": "owner-a"},
            "owner-b",
        )
