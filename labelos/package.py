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
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        return [f"manifest.json is invalid JSON: {error}"]
    if not isinstance(manifest, dict):
        return ["manifest.json must contain a JSON object"]
    if manifest.get("schema_version") != 1:
        return ["manifest.json has an unsupported schema version"]
    failures = []
    for key in ("artwork", "validation_report"):
        failures.extend(_verify_entry(destination, key, manifest.get(key)))
    return failures


def _verify_entry(destination: Path, key: str, entry: object) -> list[str]:
    if not isinstance(entry, dict):
        return [f"{key} manifest entry is invalid"]
    filename = entry.get("file")
    if not isinstance(filename, str) or not filename or Path(filename).name != filename:
        return [f"{key} file path is invalid"]
    expected_hash = entry.get("sha256")
    if not isinstance(expected_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
        return [f"{key} checksum is invalid"]
    path = destination / filename
    if path.is_symlink() or not path.is_file():
        return [f"{key} file is missing: {filename}"]
    if expected_hash != _sha256(path):
        return [f"{key} checksum mismatch: {filename}"]
    return []


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
