"""Create traceable production release packages from passing validation reports."""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from .models import LabelSpec, Report

MANIFEST_SCHEMA_VERSION = 1
REQUIRED_MANIFEST_FILES = ("artwork", "validation_report")


def create_package(spec: LabelSpec, report: Report, destination: Path) -> Path:
    """Create an immutable-style package directory and return its manifest path."""
    if not report.passed:
        raise ValueError("Refusing to package artwork with validation errors")
    destination = destination.resolve()
    if destination.exists():
        raise FileExistsError(f"Package destination already exists: {destination}")
    destination.mkdir(parents=True)
    artwork_destination = destination / spec.artwork.name
    shutil.copy2(spec.artwork, artwork_destination)
    report_path = destination / "validation-report.json"
    report_path.write_text(json.dumps(report.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "artwork": {
            "file": artwork_destination.name,
            "sha256": _sha256(artwork_destination),
            "bytes": artwork_destination.stat().st_size,
        },
        "validation_report": {
            "file": report_path.name,
            "sha256": _sha256(report_path),
            "passed": report.passed,
        },
        "spec": report.metadata.get("spec", {}),
    }
    manifest_path = destination / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest_path


def verify_package(destination: Path) -> list[str]:
    """Return integrity failures for a release package."""
    manifest_path = destination / "manifest.json"
    if not manifest_path.is_file():
        return ["manifest.json is missing"]
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        return [f"manifest.json is invalid JSON: {error}"]
    if not isinstance(manifest, dict):
        return ["manifest.json root must be an object"]
    if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        return [f"unsupported manifest schema version: {manifest.get('schema_version')!r}"]

    failures: list[str] = []
    for key in REQUIRED_MANIFEST_FILES:
        entry = manifest.get(key)
        if not isinstance(entry, dict):
            failures.append(f"{key} manifest entry is missing or invalid")
            continue
        filename = entry.get("file")
        checksum = entry.get("sha256")
        if not _is_safe_package_filename(filename):
            failures.append(f"{key} file name is invalid")
            continue
        if not _is_sha256(checksum):
            failures.append(f"{key} checksum is invalid")
            continue
        path = destination / filename
        if not path.is_file():
            failures.append(f"{key} file is missing: {path.name}")
        elif checksum != _sha256(path):
            failures.append(f"{key} checksum mismatch: {path.name}")
    validation_report = manifest.get("validation_report")
    if isinstance(validation_report, dict) and validation_report.get("passed") is not True:
        failures.append("validation_report must record a passing validation result")
    return failures


def _is_safe_package_filename(value: object) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and Path(value).name == value
        and "/" not in value
        and "\\" not in value
        and value not in {".", ".."}
    )


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
