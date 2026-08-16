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
    """Return structural, integrity, and validation-report failures for a release package."""
    if destination.is_symlink() or not destination.is_dir():
        return ["package destination must be a non-symlink directory"]
    manifest_path = destination / "manifest.json"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        return ["manifest.json is missing"]
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        return [f"manifest.json is invalid JSON: {error}"]
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 2:
        return ["manifest schema_version must be 2"]

    failures: list[str] = []
    entries: dict[str, tuple[str, dict[str, Any]]] = {}
    for key in ("artwork", "validation_report"):
        entry = manifest.get(key)
        if not isinstance(entry, dict):
            failures.append(f"manifest {key} entry is invalid")
            continue
        filename = entry.get("file")
        if not _is_safe_filename(filename):
            failures.append(f"manifest {key} file path is unsafe")
            continue
        entries[key] = (filename, entry)

    expected_files = {"manifest.json"}
    expected_files.update(filename for filename, _ in entries.values())
    if len(expected_files) != len(entries) + 1:
        failures.append("manifest entries must use distinct file names")
    for path in destination.iterdir():
        if path.is_symlink() or not path.is_file():
            failures.append(f"package contains non-regular file: {path.name}")
        elif path.name not in expected_files:
            failures.append(f"package contains unexpected file: {path.name}")

    for key, (filename, entry) in entries.items():
        path = destination / filename
        if path.is_symlink() or not path.is_file():
            failures.append(f"{key} file is missing: {filename}")
            continue
        if entry.get("bytes") != path.stat().st_size:
            failures.append(f"{key} byte count mismatch: {filename}")
        checksum = entry.get("sha256")
        if not isinstance(checksum, str) or len(checksum) != 64:
            failures.append(f"{key} checksum is invalid: {filename}")
        elif checksum != _sha256(path):
            failures.append(f"{key} checksum mismatch: {filename}")

    report_entry = entries.get("validation_report")
    if report_entry:
        _, entry = report_entry
        report = _read_report(destination / entry["file"])
        if report is None:
            failures.append("validation report is invalid JSON")
        elif report.get("passed") is not True:
            failures.append("validation report does not pass")
        elif not isinstance(report.get("metadata"), dict) or (
            report["metadata"].get("spec") != manifest.get("spec")
        ):
            failures.append("validation report spec does not match manifest")
    return failures


def _is_safe_filename(value: Any) -> bool:
    return isinstance(value, str) and bool(value) and Path(value).name == value and value not in {".", ".."}


def _read_report(path: Path) -> dict[str, Any] | None:
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return report if isinstance(report, dict) else None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
