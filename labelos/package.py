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
        "schema_version": 1,
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
    if destination.is_symlink():
        return ["package destination must not be a symlink"]
    if not destination.is_dir():
        return ["package destination is missing or not a directory"]
    manifest_path = destination / "manifest.json"
    if not manifest_path.is_file():
        return ["manifest.json is missing"]
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        return [f"manifest.json is invalid JSON: {error}"]
    if not isinstance(manifest, dict):
        return ["manifest.json root must be an object"]
    failures = _validate_manifest(manifest)
    expected_files = {"manifest.json"}
    for key in ("artwork", "validation_report"):
        entry = manifest.get(key)
        if not isinstance(entry, dict):
            continue
        filename = entry.get("file")
        if not isinstance(filename, str) or not _is_safe_filename(filename):
            continue
        expected_files.add(filename)
        path = destination / filename
        if path.is_symlink():
            failures.append(f"{key} file must not be a symlink: {filename}")
        elif not path.is_file():
            failures.append(f"{key} file is missing: {filename}")
        else:
            if entry.get("sha256") != _sha256(path):
                failures.append(f"{key} checksum mismatch: {filename}")
            if entry.get("bytes") != path.stat().st_size:
                failures.append(f"{key} byte count mismatch: {filename}")
    for path in destination.rglob("*"):
        relative = path.relative_to(destination)
        if path.is_symlink():
            failures.append(f"package must not contain symlinks: {relative}")
        elif path.is_dir():
            failures.append(f"package must not contain subdirectories: {relative}")
        elif str(relative) not in expected_files:
            failures.append(f"unexpected package file: {relative}")
    return failures


def _validate_manifest(manifest: dict[str, Any]) -> list[str]:
    failures = []
    if manifest.get("schema_version") != 1:
        failures.append("manifest schema_version must be 1")
    required_keys = {"schema_version", "created_at", "artwork", "validation_report", "spec"}
    missing = sorted(required_keys - manifest.keys())
    if missing:
        failures.append(f"manifest is missing required fields: {', '.join(missing)}")
    unexpected = sorted(set(manifest) - required_keys)
    if unexpected:
        failures.append(f"manifest has unexpected fields: {', '.join(unexpected)}")
    try:
        datetime.fromisoformat(str(manifest.get("created_at", "")).replace("Z", "+00:00"))
    except ValueError:
        failures.append("manifest created_at must be an ISO 8601 timestamp")
    for key in ("artwork", "validation_report"):
        entry = manifest.get(key)
        if not isinstance(entry, dict):
            failures.append(f"manifest {key} must be an object")
            continue
        filename = entry.get("file")
        if not isinstance(filename, str) or not _is_safe_filename(filename):
            failures.append(f"manifest {key} file must be a single filename")
        digest = entry.get("sha256")
        if not isinstance(digest, str) or not _is_sha256(digest):
            failures.append(f"manifest {key} sha256 must be a SHA-256 hex digest")
        if not isinstance(entry.get("bytes"), int) or entry["bytes"] < 0:
            failures.append(f"manifest {key} bytes must be a non-negative integer")
    report = manifest.get("validation_report")
    if isinstance(report, dict) and report.get("passed") is not True:
        failures.append("manifest validation_report passed must be true")
    if not isinstance(manifest.get("spec"), dict):
        failures.append("manifest spec must be an object")
    return failures


def _is_safe_filename(filename: str) -> bool:
    return Path(filename).name == filename and filename not in {".", ".."} and "/" not in filename and "\\" not in filename


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value.lower())


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
