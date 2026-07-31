from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pytest


def require_repository_paths(
    repository_root: Path,
    relative_paths: Iterable[str | Path],
    *,
    purpose: str,
) -> None:
    missing = tuple(
        str(relative_path)
        for relative_path in relative_paths
        if not (repository_root / relative_path).exists()
    )
    if missing:
        preview = ", ".join(missing[:3])
        if len(missing) > 3:
            preview = f"{preview}, and {len(missing) - 3} more"
        pytest.skip(
            f"{purpose} requires gitignored controlled local data; "
            f"missing: {preview}"
        )


def require_artifact_controlled_references(
    repository_root: Path,
    artifact_paths: Iterable[str | Path],
    *,
    purpose: str,
) -> None:
    references: set[str] = set()
    for relative_path in artifact_paths:
        artifact_path = repository_root / relative_path
        if not artifact_path.is_file():
            pytest.skip(
                f"{purpose} requires a Git-safe manifest that is unavailable: "
                f"{relative_path}"
            )
        payload = json.loads(artifact_path.read_text(encoding="utf-8"))
        references.update(_storage_references(payload))
    require_repository_paths(
        repository_root,
        sorted(references),
        purpose=purpose,
    )


def _storage_references(value: Any) -> set[str]:
    references: set[str] = set()
    if isinstance(value, dict):
        for child in value.values():
            references.update(_storage_references(child))
    elif isinstance(value, list):
        for child in value:
            references.update(_storage_references(child))
    elif isinstance(value, str):
        normalized = value.replace("\\", "/")
        if normalized.startswith("storage/"):
            references.add(normalized)
    return references
