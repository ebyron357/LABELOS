"""Create traceable production release packages from passing validation reports."""

from __future__ import annotations

import hashlib
import json
import re
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
    manifest_path = destination / "manifest.json"
    if not manifest_path.is_file():
        return ["manifest.json is missing"]
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        return [f"manifest.json is invalid JSON: {error}"]
    if not isinstance(manifest, dict):
        return ["manifest root must be an object"]
    if manifest.get("schema_version") != 1:
        return ["manifest schema_version must be 1"]

    failures: list[str] = []
    for key in ("artwork", "validation_report"):
        entry = manifest.get(key)
        if not isinstance(entry, dict):
            failures.append(f"manifest {key} entry must be an object")
            continue
        filename = entry.get("file")
        if not _is_package_filename(filename):
            failures.append(f"{key} file must be a package-relative filename")
            continue
        checksum = entry.get("sha256")
        if not isinstance(checksum, str) or not re.fullmatch(r"[0-9a-f]{64}", checksum):
            failures.append(f"{key} sha256 must be a lowercase 64-character hex digest")
            continue
        expected_bytes = entry.get("bytes")
        if not isinstance(expected_bytes, int) or isinstance(expected_bytes, bool) or expected_bytes < 0:
            failures.append(f"{key} bytes must be a non-negative integer")
            continue
        path = destination / filename
        if not path.is_file():
            failures.append(f"{key} file is missing: {path.name}")
        elif checksum != _sha256(path):
            failures.append(f"{key} checksum mismatch: {path.name}")
        elif expected_bytes != path.stat().st_size:
            failures.append(f"{key} byte count mismatch: {path.name}")
    report_entry = manifest.get("validation_report")
    if isinstance(report_entry, dict) and report_entry.get("passed") is not True:
        failures.append("validation_report passed must be true")
    return failures


def _is_package_filename(value: object) -> bool:
    """Allow only one normal file name, preventing manifest path traversal."""
    return isinstance(value, str) and bool(value) and Path(value).name == value and value not in {".", ".."}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
