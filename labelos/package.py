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
    if spec.artwork.name in {"manifest.json", "validation-report.json"}:
        raise ValueError("Artwork filename conflicts with a reserved package filename")
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
    manifest_path = destination / "manifest.json"
    if destination.is_symlink() or not destination.is_dir():
        return ["package destination is not a regular directory"]
    if manifest_path.is_symlink() or not manifest_path.is_file():
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
    entries = {
        "artwork": manifest.get("artwork"),
        "validation_report": manifest.get("validation_report"),
    }
    files: dict[str, Path] = {}
    for key, entry in entries.items():
        if not isinstance(entry, dict):
            failures.append(f"{key} entry is missing or invalid")
            continue
        filename = entry.get("file")
        if not _safe_filename(filename):
            failures.append(f"{key} file name is unsafe")
            continue
        files[key] = destination / filename
    expected_files = {"manifest.json"} | {path.name for path in files.values()}
    actual_files = {path.name for path in destination.iterdir()}
    unexpected = sorted(actual_files - expected_files)
    if unexpected:
        failures.append(f"package contains unexpected files: {', '.join(unexpected)}")
    missing_entries = {"artwork", "validation_report"} - set(files)
    if missing_entries:
        return failures
    if len(expected_files) != 3:
        failures.append("package entries must use distinct filenames")
    for key in ("artwork", "validation_report"):
        entry = entries[key]
        path = files[key]
        if path.is_symlink() or not path.is_file():
            failures.append(f"{key} file is missing: {path.name}")
            continue
        if path.stat().st_size != entry.get("bytes"):
            failures.append(f"{key} byte size mismatch: {path.name}")
        if not isinstance(entry.get("sha256"), str) or entry["sha256"] != _sha256(path):
            failures.append(f"{key} checksum mismatch: {path.name}")
    report_path = files["validation_report"]
    if report_path.is_file() and not report_path.is_symlink():
        failures.extend(_validate_report(report_path, manifest))
    return failures


def _safe_filename(value: object) -> bool:
    return isinstance(value, str) and value not in {"", ".", ".."} and Path(value).name == value


def _validate_report(report_path: Path, manifest: dict) -> list[str]:
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        return [f"validation report is invalid JSON: {error}"]
    if not isinstance(report, dict):
        return ["validation report root must be an object"]
    failures = []
    if report.get("passed") is not True:
        failures.append("validation report does not record a passing validation")
    if report.get("metadata", {}).get("spec") != manifest.get("spec"):
        failures.append("validation report specification does not match manifest")
    return failures


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
