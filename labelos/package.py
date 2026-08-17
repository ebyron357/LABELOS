"""Create traceable production release packages from passing validation reports."""

from __future__ import annotations

import hashlib
import json
import shutil
import stat
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import LabelSpec, Report

MANIFEST_FILE = "manifest.json"
REPORT_FILE = "validation-report.json"
SCHEMA_VERSION = 1
_RESERVED_FILENAMES = frozenset({MANIFEST_FILE, REPORT_FILE})


def create_package(spec: LabelSpec, report: Report, destination: Path) -> Path:
    """Create an immutable-style package directory and return its manifest path."""
    if not report.passed:
        raise ValueError("Refusing to package artwork with validation errors")
    if spec.artwork.name in _RESERVED_FILENAMES:
        raise ValueError(f"Artwork filename is reserved by the release package: {spec.artwork.name}")
    destination = destination.resolve()
    if destination.exists():
        raise FileExistsError(f"Package destination already exists: {destination}")
    destination.mkdir(parents=True)
    artwork_destination = destination / spec.artwork.name
    shutil.copy2(spec.artwork, artwork_destination)
    report_path = destination / REPORT_FILE
    report_path.write_text(json.dumps(report.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest = {
        "schema_version": SCHEMA_VERSION,
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
    manifest_path = destination / MANIFEST_FILE
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest_path


def verify_package(destination: Path) -> list[str]:
    """Return structural and integrity failures for a release package.

    Packages are deliberately closed: only a manifest, the validated artwork, and its
    validation report are allowed. Manifest file names are restricted to plain filenames
    and symlinks are rejected so an untrusted package cannot make verification read outside
    its directory.
    """
    destination = destination.resolve()
    manifest_path = destination / MANIFEST_FILE
    if not _is_regular_file(manifest_path):
        return [f"{MANIFEST_FILE} is missing or not a regular file"]
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        return [f"{MANIFEST_FILE} is invalid JSON: {error}"]
    if not isinstance(manifest, dict):
        return [f"{MANIFEST_FILE} root must be a JSON object"]

    failures = _validate_manifest(manifest)
    if failures:
        return failures

    artwork = manifest["artwork"]
    validation_report = manifest["validation_report"]
    expected_files = {MANIFEST_FILE, artwork["file"], validation_report["file"]}
    actual_files = {path.name for path in destination.iterdir()}
    unexpected = sorted(actual_files - expected_files)
    if unexpected:
        failures.append(f"package contains unexpected files: {', '.join(unexpected)}")

    for key, entry in (("artwork", artwork), ("validation_report", validation_report)):
        path = destination / entry["file"]
        if not _is_regular_file(path):
            failures.append(f"{key} file is missing or not a regular file: {entry['file']}")
            continue
        if path.stat().st_size != entry["bytes"]:
            failures.append(f"{key} byte count mismatch: {entry['file']}")
        if entry["sha256"] != _sha256(path):
            failures.append(f"{key} checksum mismatch: {entry['file']}")

    report_path = destination / validation_report["file"]
    if _is_regular_file(report_path):
        failures.extend(_validate_report(report_path, manifest["spec"]))
    return failures


def _validate_manifest(manifest: dict[str, Any]) -> list[str]:
    expected_fields = {"schema_version", "created_at", "artwork", "validation_report", "spec"}
    failures = []
    missing = sorted(expected_fields - manifest.keys())
    unexpected = sorted(manifest.keys() - expected_fields)
    if missing:
        failures.append(f"{MANIFEST_FILE} is missing fields: {', '.join(missing)}")
    if unexpected:
        failures.append(f"{MANIFEST_FILE} has unsupported fields: {', '.join(unexpected)}")
    if missing:
        return failures
    if (
        not isinstance(manifest["schema_version"], int)
        or isinstance(manifest["schema_version"], bool)
        or manifest["schema_version"] != SCHEMA_VERSION
    ):
        failures.append(f"{MANIFEST_FILE} has unsupported schema version")
    if not _is_timestamp(manifest["created_at"]):
        failures.append(f"{MANIFEST_FILE} has invalid created_at timestamp")
    if not isinstance(manifest["spec"], dict):
        failures.append(f"{MANIFEST_FILE} spec must be an object")
    failures.extend(_validate_entry("artwork", manifest["artwork"], require_passed=False))
    failures.extend(_validate_entry("validation_report", manifest["validation_report"], require_passed=True))
    artwork = manifest.get("artwork")
    report = manifest.get("validation_report")
    if isinstance(artwork, dict) and isinstance(report, dict) and artwork.get("file") == report.get("file"):
        failures.append("artwork and validation_report must reference different files")
    return failures


def _validate_entry(name: str, entry: Any, *, require_passed: bool) -> list[str]:
    if not isinstance(entry, dict):
        return [f"{name} manifest entry must be an object"]
    expected_fields = {"file", "sha256", "bytes"}
    if require_passed:
        expected_fields.add("passed")
    if set(entry) != expected_fields:
        return [f"{name} manifest entry has invalid fields"]
    failures = []
    filename = entry["file"]
    if not _is_safe_filename(filename) or (name == "validation_report" and filename != REPORT_FILE):
        failures.append(f"{name} manifest file is not an allowed package filename")
    if name == "artwork" and filename in _RESERVED_FILENAMES:
        failures.append("artwork manifest file is reserved by the release package")
    if not _is_sha256(entry["sha256"]):
        failures.append(f"{name} manifest checksum is invalid")
    if not isinstance(entry["bytes"], int) or isinstance(entry["bytes"], bool) or entry["bytes"] < 0:
        failures.append(f"{name} manifest byte count is invalid")
    if require_passed and entry["passed"] is not True:
        failures.append("validation_report manifest must record a passing validation")
    return failures


def _validate_report(path: Path, spec: dict[str, Any]) -> list[str]:
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        return [f"validation_report is invalid JSON: {error}"]
    if not isinstance(report, dict):
        return ["validation_report root must be a JSON object"]
    if report.get("passed") is not True:
        return ["validation_report does not record a passing validation"]
    metadata = report.get("metadata")
    if not isinstance(metadata, dict) or metadata.get("spec") != spec:
        return ["validation_report spec does not match manifest spec"]
    return []


def _is_regular_file(path: Path) -> bool:
    try:
        return stat.S_ISREG(path.lstat().st_mode)
    except OSError:
        return False


def _is_safe_filename(value: Any) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and "/" not in value
        and "\\" not in value
        and "\x00" not in value
        and Path(value).name == value
        and value not in {".", ".."}
    )


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def _is_timestamp(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo is not None
    except ValueError:
        return False


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
