"""Create traceable production release packages from passing validation reports."""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import LabelSpec, Report

MANIFEST_SCHEMA_VERSION = 2
_PACKAGE_FILES = frozenset({"manifest.json", "validation-report.json"})


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
            "bytes": report_path.stat().st_size,
            "passed": report.passed,
        },
        "spec": report.metadata.get("spec", {}),
    }
    manifest_path = destination / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest_path


def verify_package(destination: Path) -> list[str]:
    """Return integrity failures for a release package."""
    if destination.is_symlink() or not destination.is_dir():
        return ["package destination is not a regular directory"]
    manifest_path = destination / "manifest.json"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        return ["manifest.json is missing"]
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        return [f"manifest.json is invalid JSON: {error}"]
    if not isinstance(manifest, dict):
        return ["manifest.json root must be an object"]
    if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        return [f"unsupported manifest schema version: {manifest.get('schema_version')!r}"]

    failures = _validate_manifest_shape(manifest)
    entries = {key: manifest.get(key) for key in ("artwork", "validation_report")}
    package_files = set(_PACKAGE_FILES)
    for key, entry in entries.items():
        if not isinstance(entry, dict):
            continue
        filename = entry.get("file")
        if _safe_filename(filename):
            package_files.add(filename)
        else:
            failures.append(f"{key} file path is unsafe")

    for path in sorted(destination.iterdir(), key=lambda item: item.name):
        if path.name not in package_files:
            failures.append(f"unexpected package file: {path.name}")
        elif path.is_symlink() or not path.is_file():
            failures.append(f"package file is not a regular file: {path.name}")

    for key, entry in entries.items():
        if not _valid_entry(entry, key) or not _safe_filename(entry["file"]):
            continue
        path = destination / entry["file"]
        if path.is_symlink() or not path.is_file():
            failures.append(f"{key} file is missing: {path.name}")
            continue
        if entry["bytes"] != path.stat().st_size:
            failures.append(f"{key} byte count mismatch: {path.name}")
        if entry["sha256"] != _sha256(path):
            failures.append(f"{key} checksum mismatch: {path.name}")

    report_entry = entries["validation_report"]
    if isinstance(report_entry, dict) and _safe_filename(report_entry.get("file")):
        report_path = destination / report_entry["file"]
        if report_path.is_file() and not report_path.is_symlink():
            failures.extend(_validate_report(report_path, manifest))
    return failures


def _validate_manifest_shape(manifest: dict[str, Any]) -> list[str]:
    required = {"schema_version", "created_at", "artwork", "validation_report", "spec"}
    failures = []
    if set(manifest) != required:
        failures.append("manifest.json has unexpected or missing fields")
    for key in ("artwork", "validation_report"):
        entry = manifest.get(key)
        if not isinstance(entry, dict) or set(entry) != {"file", "sha256", "bytes"} | (
            {"passed"} if key == "validation_report" else set()
        ):
            failures.append(f"{key} manifest entry is malformed")
            continue
        if not isinstance(entry["sha256"], str) or not _is_sha256(entry["sha256"]):
            failures.append(f"{key} checksum is malformed")
        if not isinstance(entry["bytes"], int) or entry["bytes"] < 0:
            failures.append(f"{key} byte count is malformed")
    if not isinstance(manifest.get("created_at"), str):
        failures.append("manifest created_at is malformed")
    if not isinstance(manifest.get("spec"), dict):
        failures.append("manifest spec is malformed")
    report_entry = manifest.get("validation_report")
    if not isinstance(report_entry, dict) or report_entry.get("passed") is not True:
        failures.append("manifest validation report is not passing")
    return failures


def _validate_report(path: Path, manifest: dict[str, Any]) -> list[str]:
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return ["validation report is invalid JSON"]
    if not isinstance(report, dict) or report.get("passed") is not True:
        return ["validation report is not passing"]
    metadata = report.get("metadata")
    if not isinstance(metadata, dict) or metadata.get("spec") != manifest.get("spec"):
        return ["validation report spec does not match manifest"]
    return []


def _safe_filename(value: object) -> bool:
    return (
        isinstance(value, str)
        and Path(value).name == value
        and "/" not in value
        and "\\" not in value
        and value not in {"", ".", ".."}
    )


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def _valid_entry(entry: object, key: str) -> bool:
    if not isinstance(entry, dict):
        return False
    required = {"file", "sha256", "bytes"} | ({"passed"} if key == "validation_report" else set())
    return set(entry) == required and isinstance(entry["bytes"], int) and isinstance(entry["sha256"], str)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
