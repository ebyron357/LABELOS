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
    """Return integrity and structure failures for a release package.

    A package is a closed directory: its manifest must describe every regular file and
    no symlinks or paths outside the directory are accepted.
    """
    manifest_path = destination / "manifest.json"
    if not manifest_path.is_file():
        return ["manifest.json is missing"]
    if manifest_path.is_symlink():
        return ["manifest.json must not be a symlink"]
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        return [f"manifest.json is invalid JSON: {error}"]
    if not isinstance(manifest, dict):
        return ["manifest.json must contain an object"]
    failures: list[str] = []
    if manifest.get("schema_version") != 2:
        failures.append("unsupported manifest schema_version")
    entries: dict[str, Path] = {}
    for key in ("artwork", "validation_report"):
        entry = manifest.get(key)
        if not isinstance(entry, dict):
            failures.append(f"{key} entry is missing or invalid")
            continue
        filename = entry.get("file")
        if not isinstance(filename, str) or not _safe_filename(filename):
            failures.append(f"{key} file name is invalid")
            continue
        path = destination / filename
        entries[key] = path
        if not path.is_file():
            failures.append(f"{key} file is missing: {filename}")
            continue
        if path.is_symlink():
            failures.append(f"{key} file must not be a symlink: {filename}")
            continue
        if not isinstance(entry.get("bytes"), int) or entry["bytes"] < 0:
            failures.append(f"{key} byte count is invalid: {filename}")
        elif path.stat().st_size != entry["bytes"]:
            failures.append(f"{key} byte count mismatch: {filename}")
        checksum = entry.get("sha256")
        if not isinstance(checksum, str) or not _valid_sha256(checksum):
            failures.append(f"{key} checksum is invalid: {filename}")
        elif checksum != _sha256(path):
            failures.append(f"{key} checksum mismatch: {filename}")
    _check_closed_directory(destination, {"manifest.json", *(path.name for path in entries.values())}, failures)
    report_path = entries.get("validation_report")
    report_entry = manifest.get("validation_report")
    if report_path is not None and report_path.is_file() and not report_path.is_symlink():
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            failures.append(f"validation report is invalid JSON: {error}")
        else:
            if not isinstance(report, dict) or report.get("passed") is not True:
                failures.append("validation report does not record a passing result")
            if not isinstance(report_entry, dict) or report_entry.get("passed") is not True:
                failures.append("manifest does not record a passing validation result")
            elif isinstance(report, dict):
                metadata = report.get("metadata")
                if not isinstance(metadata, dict) or metadata.get("spec") != manifest.get("spec"):
                    failures.append("manifest spec does not match validation report")
    return failures


def _safe_filename(value: str) -> bool:
    return value == Path(value).name and value not in {"", ".", ".."}


def _valid_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value.lower())


def _check_closed_directory(destination: Path, expected: set[str], failures: list[str]) -> None:
    for child in destination.iterdir():
        if child.is_symlink():
            failures.append(f"package contains symlink: {child.name}")
        elif not child.is_file():
            failures.append(f"package contains non-file entry: {child.name}")
        elif child.name not in expected:
            failures.append(f"package contains untracked file: {child.name}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
