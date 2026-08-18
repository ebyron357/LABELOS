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
        return ["manifest.json must contain a JSON object"]
    failures = []
    if manifest.get("schema_version") != 1:
        failures.append("manifest schema_version must be 1")
    for key in ("artwork", "validation_report"):
        entry = manifest.get(key, {})
        if not isinstance(entry, dict):
            failures.append(f"{key} manifest entry must be an object")
            continue
        filename, expected_hash = entry.get("file"), entry.get("sha256")
        if not isinstance(filename, str) or not filename or Path(filename).name != filename:
            failures.append(f"{key} file must be a package-relative filename")
            continue
        if not isinstance(expected_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
            failures.append(f"{key} sha256 must be a lowercase SHA-256 digest")
            continue
        path = destination / filename
        if path.is_symlink() or not path.is_file():
            failures.append(f"{key} file is missing: {filename}")
        elif expected_hash != _sha256(path):
            failures.append(f"{key} checksum mismatch: {filename}")
    report = manifest.get("validation_report")
    if isinstance(report, dict) and isinstance(report.get("file"), str):
        report_path = destination / report["file"]
        if report_path.is_file() and _report_is_not_passing(report_path):
            failures.append("validation report does not record a passing result")
    return failures


def _report_is_not_passing(path: Path) -> bool:
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return True
    return not isinstance(report, dict) or report.get("passed") is not True


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
