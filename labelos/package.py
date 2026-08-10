"""Create traceable production release packages from passing validation reports."""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import LabelSpec, Report

MANIFEST_SCHEMA_VERSION = 1
_SHA256_LENGTH = 64


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
    package_spec = report.metadata.get("spec")
    if not isinstance(package_spec, dict):
        raise TypeError("Validation report does not contain a canonical label specification")
    spec_path = destination / "label-spec.json"
    spec_path.write_text(json.dumps(package_spec, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report_path = destination / "validation-report.json"
    report_path.write_text(json.dumps(report.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "artwork": _manifest_entry(artwork_destination),
        "label_spec": _manifest_entry(spec_path),
        "validation_report": {**_manifest_entry(report_path), "passed": report.passed},
        "spec": package_spec,
    }
    manifest_path = destination / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest_path


def verify_package(destination: Path) -> list[str]:
    """Return integrity failures for a release package."""
    manifest_path = destination / "manifest.json"
    if not _is_regular_file(manifest_path):
        return ["manifest.json is missing"]
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        return [f"manifest.json is invalid JSON: {error}"]
    if not isinstance(manifest, dict):
        return ["manifest.json root must be an object"]
    failures: list[str] = []
    if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        failures.append(f"unsupported manifest schema version: {manifest.get('schema_version')!r}")
    package_spec = manifest.get("spec")
    if not isinstance(package_spec, dict):
        failures.append("manifest spec must be an object")
    entries: dict[str, Path] = {}
    for key in ("artwork", "label_spec", "validation_report"):
        path = _verify_entry(destination, key, manifest.get(key), failures)
        if path is not None:
            entries[key] = path
    report_entry = manifest.get("validation_report")
    if not isinstance(report_entry, dict) or report_entry.get("passed") is not True:
        failures.append("validation_report must record a passing validation result")
    if "label_spec" in entries and isinstance(package_spec, dict):
        _verify_json_matches(entries["label_spec"], "label_spec", package_spec, failures)
    if "validation_report" in entries and isinstance(package_spec, dict):
        _verify_report(entries["validation_report"], package_spec, failures)
    return failures


def _manifest_entry(path: Path) -> dict[str, str | int]:
    return {"file": path.name, "sha256": _sha256(path), "bytes": path.stat().st_size}


def _verify_entry(destination: Path, key: str, entry: Any, failures: list[str]) -> Path | None:
    if not isinstance(entry, dict):
        failures.append(f"{key} manifest entry must be an object")
        return None
    filename = entry.get("file")
    if not isinstance(filename, str) or Path(filename).name != filename or not filename:
        failures.append(f"{key} file must be a package-local filename")
        return None
    path = destination / filename
    if not _is_regular_file(path):
        failures.append(f"{key} file is missing or not a regular file: {filename}")
        return None
    digest = entry.get("sha256")
    if (
        not isinstance(digest, str)
        or len(digest) != _SHA256_LENGTH
        or digest != digest.lower()
        or any(char not in "0123456789abcdef" for char in digest)
    ):
        failures.append(f"{key} sha256 must be a lowercase SHA-256 digest")
    elif digest != _sha256(path):
        failures.append(f"{key} checksum mismatch: {filename}")
    if not isinstance(entry.get("bytes"), int) or isinstance(entry.get("bytes"), bool):
        failures.append(f"{key} bytes must be an integer")
    elif entry["bytes"] != path.stat().st_size:
        failures.append(f"{key} byte count mismatch: {filename}")
    return path


def _verify_json_matches(path: Path, key: str, expected: dict, failures: list[str]) -> None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        failures.append(f"{key} is not valid JSON: {error}")
        return
    if value != expected:
        failures.append(f"{key} does not match manifest spec")


def _verify_report(path: Path, package_spec: dict, failures: list[str]) -> None:
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        failures.append(f"validation_report is not valid JSON: {error}")
        return
    if not isinstance(report, dict) or report.get("passed") is not True:
        failures.append("validation_report does not contain a passing result")
    elif report.get("metadata", {}).get("spec") != package_spec:
        failures.append("validation_report spec does not match manifest spec")


def _is_regular_file(path: Path) -> bool:
    return path.is_file() and not path.is_symlink()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
