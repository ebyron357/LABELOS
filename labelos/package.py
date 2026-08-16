"""Create traceable production release packages from passing validation reports."""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import LabelSpec, Report


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
        "schema_version": 2,
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
    """Return integrity and release-consistency failures for a release package."""
    destination = destination.resolve()
    if not destination.is_dir():
        return [f"package directory is missing: {destination}"]
    manifest_path = destination / "manifest.json"
    if not manifest_path.is_file():
        return ["manifest.json is missing"]
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        return [f"manifest.json is invalid JSON: {error}"]
    if not isinstance(manifest, dict):
        return ["manifest.json root must be an object"]
    if manifest.get("schema_version") != 2:
        return ["manifest.json has an unsupported schema version"]

    failures: list[str] = []
    expected_files = {"manifest.json"}
    for key in ("artwork", "validation_report"):
        entry = manifest.get(key)
        if not isinstance(entry, dict):
            failures.append(f"{key} entry is missing or invalid")
            continue
        filename = entry.get("file")
        if not _safe_package_filename(filename):
            failures.append(f"{key} file path is unsafe")
            continue
        expected_files.add(filename)
        path = destination / filename
        if not path.is_file() or path.is_symlink():
            failures.append(f"{key} file is missing or not a regular file: {filename}")
            continue
        if entry.get("bytes") != path.stat().st_size:
            failures.append(f"{key} byte count mismatch: {filename}")
        if entry.get("sha256") != _sha256(path):
            failures.append(f"{key} checksum mismatch: {filename}")

    report_entry = manifest.get("validation_report")
    if isinstance(report_entry, dict) and _safe_package_filename(report_entry.get("file")):
        report_path = destination / report_entry["file"]
        if report_path.is_file() and not report_path.is_symlink():
            failures.extend(_validate_report(report_path, manifest))

    actual_files = {path.name for path in destination.iterdir()}
    unexpected_files = sorted(actual_files - expected_files)
    if unexpected_files:
        failures.append(f"unexpected package files: {', '.join(unexpected_files)}")
    return failures


def _safe_package_filename(value: Any) -> bool:
    return (
        isinstance(value, str)
        and Path(value).name == value
        and "/" not in value
        and "\\" not in value
        and value not in {"", ".", ".."}
    )


def _validate_report(report_path: Path, manifest: dict[str, Any]) -> list[str]:
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        return [f"validation report is invalid JSON: {error}"]
    if not isinstance(report, dict):
        return ["validation report root must be an object"]
    if report.get("passed") is not True:
        return ["validation report does not record a passing validation"]
    metadata = report.get("metadata")
    if not isinstance(metadata, dict):
        return ["validation report metadata must be an object"]
    if metadata.get("spec") != manifest.get("spec"):
        return ["validation report specification does not match manifest"]
    return []


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
