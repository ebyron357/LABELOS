"""Path and identifier sanitization for fail-closed filesystem operations."""

from __future__ import annotations

import re
from pathlib import Path

from .errors import INPUT_ERROR, LabelosException

_SAFE_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SAFE_SKU = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_SAFE_REVISION = re.compile(r"^[0-9]+(?:\.[0-9]+){0,3}$")
_SAFE_JOB = re.compile(r"^JOB-[A-Za-z0-9-]{8,64}$")


def sanitize_token(value: str, *, field: str = "name") -> str:
    """Reject empty / path-like / unsafe filesystem tokens."""
    if not isinstance(value, str):
        raise LabelosException(
            f"{field} must be a string",
            code="INVALID_TOKEN",
            category=INPUT_ERROR,
        )
    cleaned = value.strip()
    if not cleaned or cleaned in {".", ".."} or "/" in cleaned or "\\" in cleaned:
        raise LabelosException(
            f"Invalid {field}: path separators and empty values are not allowed",
            code="INVALID_TOKEN",
            category=INPUT_ERROR,
        )
    if not _SAFE_TOKEN.match(cleaned):
        raise LabelosException(
            f"Invalid {field}: use only letters, numbers, '.', '_', '-'",
            code="INVALID_TOKEN",
            category=INPUT_ERROR,
        )
    return cleaned


def sanitize_sku(value: str) -> str:
    cleaned = sanitize_token(value, field="sku")
    if not _SAFE_SKU.match(cleaned):
        raise LabelosException("Invalid SKU format", code="INVALID_SKU", category=INPUT_ERROR)
    return cleaned


def sanitize_revision(value: str) -> str:
    cleaned = value.strip()
    if not _SAFE_REVISION.match(cleaned):
        raise LabelosException(
            "Invalid revision: expected dotted numeric form like 1.0",
            code="INVALID_REVISION",
            category=INPUT_ERROR,
        )
    return cleaned


def sanitize_job_id(value: str) -> str:
    cleaned = value.strip()
    if not _SAFE_JOB.match(cleaned):
        raise LabelosException("Invalid job_id format", code="INVALID_JOB_ID", category=INPUT_ERROR)
    return cleaned


def resolve_under(root: Path, candidate: str | Path, *, field: str = "path") -> Path:
    """Resolve candidate under root and reject directory traversal."""
    root = root.resolve()
    raw = Path(candidate)
    if raw.is_absolute():
        target = raw.resolve()
    else:
        target = (root / raw).resolve()
    try:
        target.relative_to(root)
    except ValueError as error:
        raise LabelosException(
            f"{field} escapes storage root",
            code="PATH_TRAVERSAL",
            category=INPUT_ERROR,
            details={"root": str(root), "path": str(candidate)},
        ) from error
    return target


def ensure_parent_under(root: Path, destination: Path) -> Path:
    """Ensure destination parent exists under root; never overwrite existing destinations."""
    destination = resolve_under(root, destination, field="destination")
    if destination.exists():
        raise LabelosException(
            f"Destination already exists: {destination}",
            code="DESTINATION_EXISTS",
            category=INPUT_ERROR,
            http_status=409,
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    return destination
