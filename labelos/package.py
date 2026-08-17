"""Create traceable production release packages from passing validation reports."""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

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
    """Return integrity failures for a release package."""
    if destination.is_symlink() or not destination.is_dir():
        return ["package destination is missing, not a directory, or a symlink"]
    manifest_path = destination / "manifest.json"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        return ["manifest.json is missing"]
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        return [f"manifest.json is invalid JSON: {error}"]
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 2:
        return ["manifest schema_version must be 2"]
    entries = {key: manifest.get(key) for key in ("artwork", "validation_report")}
    if not all(isinstance(entry, dict) for entry in entries.values()):
        return ["manifest artwork and validation_report entries must be objects"]
    filenames = {entry.get("file") for entry in entries.values()}
    if len(filenames) != 2 or any(not _safe_filename(filename) for filename in filenames):
        return ["manifest contains invalid or duplicate package filenames"]
    expected_files = {"manifest.json", *filenames}
    actual_files = {path.name for path in destination.iterdir()}
    unexpected = sorted(actual_files - expected_files)
    missing = sorted(expected_files - actual_files)
    if unexpected:
        return [f"package contains unexpected file: {name}" for name in unexpected]
    if missing:
        return [f"package file is missing: {name}" for name in missing]

    failures: list[str] = []
    for key, entry in entries.items():
        path = destination / entry["file"]
        if path.is_symlink() or not path.is_file():
            failures.append(f"{key} file is missing: {path.name}")
            continue
        if not _valid_checksum(entry.get("sha256")):
            failures.append(f"{key} checksum is invalid: {path.name}")
        elif entry["sha256"] != _sha256(path):
            failures.append(f"{key} checksum mismatch: {path.name}")
            continue
        if not _valid_byte_count(entry.get("bytes")):
            failures.append(f"{key} byte count is invalid: {path.name}")
        elif entry["bytes"] != path.stat().st_size:
            failures.append(f"{key} byte count mismatch: {path.name}")
    report_path = destination / entries["validation_report"]["file"]
    if report_path.is_file() and not report_path.is_symlink():
        failures.extend(_validate_report_consistency(report_path, manifest))
    return failures


def _safe_filename(value: object) -> bool:
    return isinstance(value, str) and value == Path(value).name and value not in {".", ".."}


def _valid_checksum(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def _valid_byte_count(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _validate_report_consistency(report_path: Path, manifest: dict) -> list[str]:
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        return [f"validation report is invalid JSON: {error}"]
    if not isinstance(report, dict) or report.get("passed") is not True:
        return ["validation report does not record a passing validation"]
    metadata = report.get("metadata")
    if not isinstance(metadata, dict) or metadata.get("spec") != manifest.get("spec"):
        return ["validation report spec does not match manifest spec"]
    return []


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
