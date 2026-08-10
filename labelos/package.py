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

PACKAGE_SCHEMA_VERSION = 1
MANIFEST_FILE = "manifest.json"
REPORT_FILE = "validation-report.json"
SPEC_FILE = "label-spec.json"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


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
    report_path = destination / REPORT_FILE
    report_path.write_text(json.dumps(report.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report_spec = report.metadata.get("spec", {})
    spec_path = destination / SPEC_FILE
    package_spec = {"artwork": artwork_destination.name, **report_spec}
    spec_path.write_text(json.dumps(package_spec, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest = {
        "schema_version": PACKAGE_SCHEMA_VERSION,
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
        "label_spec": {
            "file": spec_path.name,
            "sha256": _sha256(spec_path),
            "bytes": spec_path.stat().st_size,
        },
        "spec": report_spec,
    }
    manifest_path = destination / MANIFEST_FILE
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest_path


def verify_package(destination: Path) -> list[str]:
    """Return integrity failures for a release package."""
    if destination.is_symlink() or not destination.is_dir():
        return ["package destination must be a directory, not a symlink"]
    manifest_path = destination / MANIFEST_FILE
    if not _is_regular_file(manifest_path):
        return [f"{MANIFEST_FILE} is missing or not a regular file"]
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        return [f"{MANIFEST_FILE} is invalid JSON: {error}"]
    if not isinstance(manifest, dict):
        return [f"{MANIFEST_FILE} must contain a JSON object"]

    failures: list[str] = []
    if manifest.get("schema_version") != PACKAGE_SCHEMA_VERSION:
        failures.append(f"unsupported package schema version: {manifest.get('schema_version')!r}")
    entries: dict[str, Path] = {}
    for key in ("artwork", "validation_report", "label_spec"):
        entry = manifest.get(key)
        path = _verify_entry(destination, key, entry, failures)
        if path is not None:
            entries[key] = path
    if failures:
        return failures

    report = _read_json_object(entries["validation_report"], "validation report", failures)
    package_spec = _read_json_object(entries["label_spec"], "label specification", failures)
    manifest_spec = manifest.get("spec")
    if not isinstance(manifest_spec, dict):
        failures.append("manifest spec must be a JSON object")
    if report is not None and report.get("passed") is not True:
        failures.append("validation report does not record a passing validation result")
    if report is not None and report.get("metadata", {}).get("spec") != manifest_spec:
        failures.append("validation report spec does not match manifest spec")
    if package_spec is not None:
        if package_spec.get("artwork") != entries["artwork"].name:
            failures.append("label specification artwork does not match manifest artwork")
        if {key: value for key, value in package_spec.items() if key != "artwork"} != manifest_spec:
            failures.append("label specification does not match manifest spec")
    return failures


def _verify_entry(
    destination: Path, key: str, entry: Any, failures: list[str]
) -> Path | None:
    if not isinstance(entry, dict):
        failures.append(f"{key} manifest entry must be an object")
        return None
    filename = entry.get("file")
    if not _is_package_filename(filename):
        failures.append(f"{key} file must be a package-local filename")
        return None
    path = destination / filename
    if not _is_regular_file(path):
        failures.append(f"{key} file is missing or not a regular file: {filename}")
        return None
    digest = entry.get("sha256")
    if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
        failures.append(f"{key} checksum must be a lowercase SHA-256 digest")
    elif digest != _sha256(path):
        failures.append(f"{key} checksum mismatch: {filename}")
    if not isinstance(entry.get("bytes"), int) or isinstance(entry["bytes"], bool):
        failures.append(f"{key} byte count must be an integer")
    elif entry["bytes"] != path.stat().st_size:
        failures.append(f"{key} byte count mismatch: {filename}")
    return path


def _is_package_filename(value: Any) -> bool:
    return isinstance(value, str) and Path(value).name == value and value not in {".", ".."}


def _is_regular_file(path: Path) -> bool:
    return path.is_file() and not path.is_symlink()


def _read_json_object(path: Path, label: str, failures: list[str]) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        failures.append(f"{label} is invalid JSON: {error}")
        return None
    if not isinstance(data, dict):
        failures.append(f"{label} must contain a JSON object")
        return None
    return data


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
