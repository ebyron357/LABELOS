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
    destination = destination.resolve()
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
        return ["manifest.json has an unsupported schema_version"]
    failures: list[str] = []
    expected_files = {"manifest.json"}
    for key in ("artwork", "validation_report"):
        entry = manifest.get(key, {})
        if not isinstance(entry, dict):
            failures.append(f"{key} entry must be an object")
            continue
        name = entry.get("file")
        if not isinstance(name, str) or not _is_safe_filename(name):
            failures.append(f"{key} file name is unsafe")
            continue
        expected_files.add(name)
        path = destination / name
        if not path.is_file() or path.is_symlink():
            failures.append(f"{key} file is missing or unsafe: {name}")
            continue
        expected_hash = entry.get("sha256")
        if not isinstance(expected_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
            failures.append(f"{key} checksum is invalid: {name}")
        elif expected_hash != _sha256(path):
            failures.append(f"{key} checksum mismatch: {name}")
        if entry.get("bytes") != path.stat().st_size:
            failures.append(f"{key} byte count mismatch: {name}")
    artwork_entry = manifest.get("artwork")
    report_entry = manifest.get("validation_report")
    if (
        isinstance(artwork_entry, dict)
        and isinstance(report_entry, dict)
        and artwork_entry.get("file") == report_entry.get("file")
    ):
        failures.append("artwork and validation_report must use different files")
    actual_files = {path.name for path in destination.iterdir()}
    unexpected = sorted(actual_files - expected_files)
    if unexpected:
        failures.append(f"unexpected package files: {', '.join(unexpected)}")
    failures.extend(_validate_report(destination, manifest))
    return failures


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_safe_filename(name: str) -> bool:
    return Path(name).name == name and name not in {".", ".."} and "/" not in name and "\\" not in name


def _validate_report(destination: Path, manifest: dict) -> list[str]:
    """Confirm the packaged report is a passing report for the declared specification."""

    entry = manifest.get("validation_report")
    if not isinstance(entry, dict) or not isinstance(entry.get("file"), str):
        return []
    try:
        report = json.loads((destination / entry["file"]).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ["validation report is invalid JSON"]
    if not isinstance(report, dict) or report.get("passed") is not True:
        return ["validation report does not record a passing validation"]
    if report.get("metadata", {}).get("spec") != manifest.get("spec"):
        return ["validation report specification does not match manifest"]
    return []
