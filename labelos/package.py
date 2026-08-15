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
    manifest_path = destination / "manifest.json"
    if not manifest_path.is_file():
        return ["manifest.json is missing"]
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        return [f"manifest.json is invalid JSON: {error}"]
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 2:
        return ["manifest.json has an unsupported schema version"]
    if not isinstance(manifest.get("spec"), dict):
        return ["manifest.json has an invalid spec"]
    failures = []
    package_files = {"manifest.json"}
    for key in ("artwork", "validation_report"):
        entry = manifest.get(key, {})
        if not isinstance(entry, dict):
            failures.append(f"{key} entry is invalid")
            continue
        filename = entry.get("file")
        if not _safe_package_filename(filename):
            failures.append(f"{key} file name is unsafe")
            continue
        package_files.add(filename)
        path = destination / filename
        if not path.is_file():
            failures.append(f"{key} file is missing: {path.name}")
            continue
        if path.is_symlink():
            failures.append(f"{key} file must not be a symbolic link: {path.name}")
            continue
        if not isinstance(entry.get("sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]):
            failures.append(f"{key} checksum is invalid: {path.name}")
        elif entry["sha256"] != _sha256(path):
            failures.append(f"{key} checksum mismatch: {path.name}")
        if not isinstance(entry.get("bytes"), int) or entry["bytes"] < 0:
            failures.append(f"{key} byte count is invalid: {path.name}")
        elif entry["bytes"] != path.stat().st_size:
            failures.append(f"{key} byte count mismatch: {path.name}")
    report_entry = manifest.get("validation_report")
    if isinstance(report_entry, dict) and _safe_package_filename(report_entry.get("file")):
        report_path = destination / report_entry["file"]
        if report_path.is_file():
            failures.extend(_verify_report(report_path, report_entry, manifest["spec"]))
    artifact_paths = list(destination.rglob("*"))
    symbolic_links = sorted(
        path.relative_to(destination).as_posix() for path in artifact_paths if path.is_symlink()
    )
    if symbolic_links:
        failures.append(f"symbolic links are not allowed: {', '.join(symbolic_links)}")
    actual_files = {
        path.relative_to(destination).as_posix()
        for path in artifact_paths
        if path.is_file()
    }
    unexpected = sorted(actual_files - package_files)
    if unexpected:
        failures.append(f"unexpected package artifacts: {', '.join(unexpected)}")
    return failures


def _safe_package_filename(value: object) -> bool:
    return isinstance(value, str) and bool(value) and Path(value).name == value and not Path(value).is_absolute()


def _verify_report(report_path: Path, entry: dict, spec: dict) -> list[str]:
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        return [f"validation report is invalid JSON: {error}"]
    if not isinstance(report, dict):
        return ["validation report is invalid"]
    failures = []
    if entry.get("passed") is not True or report.get("passed") is not True:
        failures.append("validation report does not record a passing validation")
    metadata = report.get("metadata")
    if not isinstance(metadata, dict) or metadata.get("spec") != spec:
        failures.append("validation report spec does not match manifest")
    return failures


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
