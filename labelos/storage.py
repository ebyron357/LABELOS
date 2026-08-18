"""Durable storage abstraction. Local filesystem today; provider-agnostic interface."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any, Protocol

from .errors import STORAGE_ERROR, LabelosException
from .security import resolve_under, sanitize_job_id, sanitize_revision, sanitize_sku

STORAGE_SUBDIRS = (
    "source",
    "templates",
    "generated",
    "validation",
    "approved",
    "releases",
    "archive",
    "jobs",
    "configs",
)


class StorageBackend(Protocol):
    root: Path

    def ensure_layout(self) -> None: ...

    def path(self, *parts: str) -> Path: ...

    def write_json(self, relative: str, payload: dict[str, Any]) -> Path: ...

    def read_json(self, relative: str) -> dict[str, Any]: ...

    def copy_into(self, source: Path, relative: str) -> Path: ...


class LocalStorage:
    """Filesystem storage rooted at LABELOS_STORAGE_PATH."""

    def __init__(self, root: Path | None = None) -> None:
        configured = root or Path(os.environ.get("LABELOS_STORAGE_PATH", "storage"))
        self.root = configured.expanduser().resolve()

    def ensure_layout(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        for name in STORAGE_SUBDIRS:
            (self.root / name).mkdir(parents=True, exist_ok=True)

    def path(self, *parts: str) -> Path:
        candidate = Path(*parts) if parts else Path(".")
        return resolve_under(self.root, candidate, field="storage_path")

    def write_bytes(self, relative: str, data: bytes) -> Path:
        destination = self.path(relative)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            raise LabelosException(
                f"Refusing to overwrite existing storage object: {relative}",
                code="STORAGE_OVERWRITE",
                category=STORAGE_ERROR,
                http_status=409,
            )
        destination.write_bytes(data)
        return destination

    def write_json(self, relative: str, payload: dict[str, Any]) -> Path:
        return self.write_bytes(
            relative,
            (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8"),
        )

    def read_json(self, relative: str) -> dict[str, Any]:
        path = self.path(relative)
        if not path.is_file():
            raise LabelosException(
                f"Storage object not found: {relative}",
                code="STORAGE_MISSING",
                category=STORAGE_ERROR,
                http_status=404,
            )
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise LabelosException(
                f"Corrupt storage JSON: {relative}",
                code="STORAGE_CORRUPT",
                category=STORAGE_ERROR,
                http_status=500,
                details={"error": str(error)},
            ) from error

    def copy_into(self, source: Path, relative: str) -> Path:
        if not source.is_file():
            raise LabelosException(
                f"Source file missing: {source}",
                code="STORAGE_SOURCE_MISSING",
                category=STORAGE_ERROR,
            )
        destination = self.path(relative)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            raise LabelosException(
                f"Refusing to overwrite existing storage object: {relative}",
                code="STORAGE_OVERWRITE",
                category=STORAGE_ERROR,
                http_status=409,
            )
        shutil.copy2(source, destination)
        return destination

    def release_dir(self, sku: str, revision: str, job_id: str) -> Path:
        return self.path(
            "releases",
            sanitize_sku(sku),
            sanitize_revision(revision),
            sanitize_job_id(job_id),
        )


def get_storage(root: Path | None = None) -> LocalStorage:
    storage = LocalStorage(root)
    storage.ensure_layout()
    return storage
