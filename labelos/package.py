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
REPORT_FILENAME = "validation-report.json"
MANIFEST_FILENAME = "manifest.json"


def create_package(spec: LabelSpec, report: Report, destination: Path) -> Path:
    """Create an immutable-style package directory and return its manifest path."""
    if not report.passed:
        raise ValueError("Refusing to package artwork with validation errors")
    artwork_filename = _safe_filename(spec.artwork.name)
    if artwork_filename in {REPORT_FILENAME, MANIFEST_FILENAME}:
        raise ValueError(f"Artwork filename conflicts with a package control file: {artwork_filename}")
    destination = destination.resolve()
    if destination.exists():
        raise FileExistsError(f"Package destination already exists: {destination}")
    destination.mkdir(parents=True)
    artwork_destination = destination / artwork_filename
    shutil.copy2(spec.artwork, artwork_destination)
    report_path = destination / REPORT_FILENAME
    report_path.write_text(json.dumps(report.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "artwork": _file_entry(artwork_destination),
        "validation_report": _file_entry(report_path),
        "spec": report.metadata.get("spec", {}),
    }
    manifest_path = destination / MANIFEST_FILENAME
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest_path


def verify_package(destination: Path) -> list[str]:
    """Return fail-closed integrity failures for a release package."""
    destination = destination.resolve()
    manifest_path = destination / MANIFEST_FILENAME
    if not _is_regular_file(manifest_path):
        return [f"{MANIFEST_FILENAME} is missing or is not a regular file"]
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        return [f"manifest.json is invalid JSON: {error}"]

    failures = _validate_manifest(manifest)
    if failures:
        return failures

    artwork = manifest["artwork"]
    validation_report = manifest["validation_report"]
    expected_files = {MANIFEST_FILENAME, artwork["file"], validation_report["file"]}
    actual_files = {path.name for path in destination.iterdir()}
    unexpected = sorted(actual_files - expected_files)
    missing = sorted(expected_files - actual_files)
    failures.extend(f"unexpected package file: {name}" for name in unexpected)
    failures.extend(f"package file is missing: {name}" for name in missing)

    for key, entry in (("artwork", artwork), ("validation_report", validation_report)):
        path = destination / entry["file"]
        if not _is_regular_file(path):
            failures.append(f"{key} file is missing or is not a regular file: {entry['file']}")
            continue
        byte_count = path.stat().st_size
        if byte_count != entry["bytes"]:
            failures.append(f"{key} byte count mismatch: {entry['file']}")
        if entry["sha256"] != _sha256(path):
            failures.append(f"{key} checksum mismatch: {entry['file']}")

    failures.extend(_validate_report(destination / validation_report["file"], manifest["spec"]))
    return failures


def _file_entry(path: Path) -> dict[str, str | int]:
    return {"file": path.name, "sha256": _sha256(path), "bytes": path.stat().st_size}


def _safe_filename(value: object) -> str:
    filename = str(value)
    if not filename or Path(filename).name != filename or filename in {".", ".."}:
        raise ValueError(f"Unsafe package filename: {filename!r}")
    return filename


def _validate_manifest(manifest: Any) -> list[str]:
    if not isinstance(manifest, dict):
        return ["manifest.json must contain an object"]
    if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        return [f"unsupported manifest schema_version: {manifest.get('schema_version')!r}"]
    if not isinstance(manifest.get("spec"), dict):
        return ["manifest spec must be an object"]

    failures = []
    filenames = set()
    for key, expected_filename in (("artwork", None), ("validation_report", REPORT_FILENAME)):
        entry = manifest.get(key)
        if not isinstance(entry, dict):
            failures.append(f"manifest {key} entry must be an object")
            continue
        try:
            filename = _safe_filename(entry.get("file", ""))
        except ValueError:
            failures.append(f"manifest {key} filename is unsafe")
            continue
        if expected_filename is not None and filename != expected_filename:
            failures.append(f"manifest {key} filename must be {expected_filename}")
        if filename in filenames:
            failures.append(f"manifest entries reuse filename: {filename}")
        filenames.add(filename)
        if not isinstance(entry.get("bytes"), int) or entry["bytes"] < 0:
            failures.append(f"manifest {key} byte count must be a non-negative integer")
        digest = entry.get("sha256")
        if not isinstance(digest, str) or not _is_sha256(digest):
            failures.append(f"manifest {key} SHA-256 is invalid")
    return failures


def _validate_report(report_path: Path, expected_spec: dict[str, Any]) -> list[str]:
    if not _is_regular_file(report_path):
        return []
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        return [f"validation report is invalid JSON: {error}"]
    if not isinstance(report, dict):
        return ["validation report must contain an object"]
    failures = []
    if report.get("passed") is not True:
        failures.append("validation report does not record a passing validation")
    if not isinstance(report.get("metadata"), dict) or report["metadata"].get("spec") != expected_spec:
        failures.append("validation report spec does not match manifest spec")
    return failures


def _is_regular_file(path: Path) -> bool:
    return path.is_file() and not path.is_symlink()


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value.lower())


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
