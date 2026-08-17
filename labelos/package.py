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
MANIFEST_FILENAME = "manifest.json"
REPORT_FILENAME = "validation-report.json"


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
    report_path = destination / REPORT_FILENAME
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
    manifest_path = destination / MANIFEST_FILENAME
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest_path


def verify_package(destination: Path) -> list[str]:
    """Return all integrity and structure failures for a release package."""
    destination = destination.resolve()
    manifest_path = destination / MANIFEST_FILENAME
    if not manifest_path.is_file():
        return [f"{MANIFEST_FILENAME} is missing"]
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        return [f"{MANIFEST_FILENAME} is invalid JSON: {error}"]
    if not isinstance(manifest, dict):
        return [f"{MANIFEST_FILENAME} root must be an object"]

    failures: list[str] = []
    if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        failures.append(f"unsupported manifest schema version: {manifest.get('schema_version')!r}")
    entries = {
        key: _manifest_entry(manifest, key, failures)
        for key in ("artwork", "validation_report")
    }
    expected_names = {MANIFEST_FILENAME}
    for key, entry in entries.items():
        if entry is None:
            continue
        filename = entry["file"]
        expected_names.add(filename)
        path = destination / filename
        if path.is_symlink():
            failures.append(f"{key} must not be a symbolic link: {filename}")
        elif not path.is_file():
            failures.append(f"{key} file is missing: {filename}")
        else:
            if path.stat().st_size != entry["bytes"]:
                failures.append(f"{key} byte size mismatch: {filename}")
            if entry["sha256"] != _sha256(path):
                failures.append(f"{key} checksum mismatch: {filename}")

    report_entry = entries["validation_report"]
    if report_entry is not None and (destination / report_entry["file"]).is_file():
        _validate_report(destination / report_entry["file"], manifest, failures)

    for path in destination.rglob("*"):
        relative = path.relative_to(destination)
        if path.is_symlink():
            failures.append(f"package must not contain symbolic links: {relative}")
        elif path.is_dir():
            failures.append(f"package must not contain directories: {relative}")
        elif relative.name not in expected_names:
            failures.append(f"unexpected package file: {relative}")
    return failures


def _manifest_entry(
    manifest: dict[str, Any], key: str, failures: list[str]
) -> dict[str, str | int] | None:
    entry = manifest.get(key)
    if not isinstance(entry, dict):
        failures.append(f"{key} manifest entry must be an object")
        return None
    filename, checksum, size = entry.get("file"), entry.get("sha256"), entry.get("bytes")
    if not isinstance(filename, str) or not filename or Path(filename).name != filename:
        failures.append(f"{key} manifest filename must be a non-empty basename")
        return None
    if not isinstance(checksum, str) or len(checksum) != 64 or any(
        character not in "0123456789abcdef" for character in checksum.lower()
    ):
        failures.append(f"{key} manifest SHA-256 is invalid")
    if not isinstance(size, int) or isinstance(size, bool) or size < 0:
        failures.append(f"{key} manifest byte size is invalid")
    if not isinstance(checksum, str) or not isinstance(size, int) or isinstance(size, bool):
        return None
    return {"file": filename, "sha256": checksum, "bytes": size}


def _validate_report(report_path: Path, manifest: dict[str, Any], failures: list[str]) -> None:
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        failures.append(f"validation report is invalid JSON: {error}")
        return
    if not isinstance(report, dict):
        failures.append("validation report root must be an object")
        return
    if report.get("passed") is not True:
        failures.append("validation report does not record a passing validation")
    metadata = report.get("metadata")
    if not isinstance(metadata, dict) or metadata.get("spec") != manifest.get("spec"):
        failures.append("validation report specification does not match manifest")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
