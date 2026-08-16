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
    if not manifest_path.is_file():
        return ["manifest.json is missing"]
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        return [f"manifest.json is invalid JSON: {error}"]
    if not isinstance(manifest, dict):
        return ["manifest.json must contain an object"]
    failures: list[str] = []
    if manifest.get("schema_version") != 2:
        failures.append("manifest schema_version must be 2")
    if not isinstance(manifest.get("spec"), dict) or not manifest["spec"]:
        failures.append("manifest spec is missing or invalid")
    files: dict[str, Path] = {}
    for key in ("artwork", "validation_report"):
        entry = manifest.get(key, {})
        if not isinstance(entry, dict):
            failures.append(f"{key} manifest entry is invalid")
            continue
        path = _package_file(destination, entry.get("file"))
        if path is None:
            failures.append(f"{key} file path is unsafe")
            continue
        files[key] = path
        if path.is_symlink() or not path.is_file():
            failures.append(f"{key} file is missing or not a regular file: {path.name}")
            continue
        if not isinstance(entry.get("sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]):
            failures.append(f"{key} checksum is invalid: {path.name}")
        elif entry["sha256"] != _sha256(path):
            failures.append(f"{key} checksum mismatch: {path.name}")
        if not isinstance(entry.get("bytes"), int) or entry["bytes"] != path.stat().st_size:
            failures.append(f"{key} byte count mismatch: {path.name}")
    report_path = files.get("validation_report")
    if report_path and report_path.is_file() and not report_path.is_symlink():
        _verify_report(report_path, manifest, failures)
    expected_files = {manifest_path.name, *(path.name for path in files.values())}
    actual_files = {path.name for path in destination.iterdir()} if destination.is_dir() else set()
    unexpected = sorted(actual_files - expected_files)
    if unexpected:
        failures.append(f"unexpected package files: {', '.join(unexpected)}")
    return failures


def _package_file(destination: Path, value: object) -> Path | None:
    """Return a manifest file only when it is a single safe package-relative name."""
    if (
        not isinstance(value, str)
        or value in {"", ".", ".."}
        or Path(value).name != value
    ):
        return None
    return destination / value


def _verify_report(report_path: Path, manifest: dict, failures: list[str]) -> None:
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        failures.append(f"validation report is invalid JSON: {error}")
        return
    if not isinstance(report, dict) or report.get("passed") is not True:
        failures.append("validation report does not record a passing result")
    elif report.get("metadata", {}).get("spec") != manifest.get("spec"):
        failures.append("validation report spec does not match manifest spec")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
