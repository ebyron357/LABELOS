"""Create traceable production release packages from passing validation reports."""

from __future__ import annotations

import hashlib
import json
import re
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
        return ["package destination must not be a symbolic link"]
    if not destination.is_dir():
        return ["package destination is missing or is not a directory"]
    manifest_path = destination / "manifest.json"
    if manifest_path.is_symlink():
        return ["manifest.json must not be a symbolic link"]
    if not manifest_path.is_file():
        return ["manifest.json is missing"]
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        return [f"manifest.json is invalid JSON: {error}"]
    if not isinstance(manifest, dict):
        return ["manifest.json root must be an object"]
    if manifest.get("schema_version") != 1 or isinstance(manifest.get("schema_version"), bool):
        return ["manifest.json has unsupported schema_version"]

    failures: list[str] = []
    seen_files: set[str] = set()
    for key in ("artwork", "validation_report"):
        entry = manifest.get(key)
        if not isinstance(entry, dict):
            failures.append(f"{key} manifest entry is missing or invalid")
            continue
        package_file = entry.get("file")
        if not _is_safe_package_filename(package_file):
            failures.append(f"{key} file path is unsafe")
            continue
        if package_file in seen_files:
            failures.append(f"{key} file duplicates another manifest entry: {package_file}")
            continue
        seen_files.add(package_file)
        path = destination / package_file
        if path.is_symlink():
            failures.append(f"{key} file must not be a symbolic link: {package_file}")
            continue
        if not path.is_file():
            failures.append(f"{key} file is missing: {package_file}")
            continue
        expected_bytes = entry.get("bytes")
        if not isinstance(expected_bytes, int) or isinstance(expected_bytes, bool) or expected_bytes < 0:
            failures.append(f"{key} byte count is missing or invalid")
        elif path.stat().st_size != expected_bytes:
            failures.append(f"{key} byte count mismatch: {package_file}")
        expected_checksum = entry.get("sha256")
        if not isinstance(expected_checksum, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_checksum):
            failures.append(f"{key} checksum is missing or invalid")
        elif expected_checksum != _sha256(path):
            failures.append(f"{key} checksum mismatch: {package_file}")
        if key == "validation_report" and entry.get("passed") is not True:
            failures.append("validation_report must record a passing validation result")
    return failures


def _is_safe_package_filename(value: Any) -> bool:
    """Allow only a single regular filename in a release package."""
    if not isinstance(value, str) or not value:
        return False
    path = Path(value)
    return not path.is_absolute() and path.name == value and value not in {".", ".."}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
