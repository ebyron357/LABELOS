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

MANIFEST_SCHEMA_VERSION = 1
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")


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
    package_spec = _package_spec(spec, artwork_destination.name)
    report.metadata["spec"] = package_spec
    report_path.write_text(json.dumps(report.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
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
    except (OSError, json.JSONDecodeError) as error:
        return [f"manifest.json is invalid JSON: {error}"]
    if not isinstance(manifest, dict):
        return ["manifest.json must contain a JSON object"]

    failures: list[str] = []
    if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        failures.append(f"unsupported manifest schema version: {manifest.get('schema_version')!r}")
    for key in ("artwork", "validation_report"):
        entry = manifest.get(key, {})
        if not isinstance(entry, dict):
            failures.append(f"{key} entry must be an object")
            continue
        filename = entry.get("file")
        if not _is_package_filename(filename):
            failures.append(f"{key} file must be a package-local filename")
            continue
        path = destination / filename
        if not _is_regular_file(path):
            failures.append(f"{key} file is missing or not a regular file: {filename}")
            continue
        checksum = entry.get("sha256")
        if not isinstance(checksum, str) or not _SHA256_PATTERN.fullmatch(checksum):
            failures.append(f"{key} sha256 must be a lowercase SHA-256 digest")
        elif checksum != _sha256(path):
            failures.append(f"{key} checksum mismatch: {filename}")
        byte_count = entry.get("bytes")
        if not isinstance(byte_count, int) or isinstance(byte_count, bool) or byte_count < 0:
            failures.append(f"{key} bytes must be a non-negative integer")
        elif byte_count != path.stat().st_size:
            failures.append(f"{key} byte count mismatch: {filename}")

    report_entry = manifest.get("validation_report")
    if isinstance(report_entry, dict) and _is_package_filename(report_entry.get("file")):
        report_path = destination / report_entry["file"]
        if _is_regular_file(report_path):
            failures.extend(_verify_report(report_path, manifest.get("spec")))
    return failures


def _package_spec(spec: LabelSpec, artwork_filename: str) -> dict[str, Any]:
    return {
        "artwork": artwork_filename,
        "width_mm": spec.width_mm,
        "height_mm": spec.height_mm,
        "trim_mm": spec.trim_mm,
        "bleed_mm": spec.bleed_mm,
        "safe_area_mm": spec.safe_area_mm,
        "min_dpi": spec.min_dpi,
        "required_copy": list(spec.required_copy),
        "barcode_value": spec.barcode_value,
        "qr_value": spec.qr_value,
    }


def _verify_report(report_path: Path, manifest_spec: object) -> list[str]:
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return [f"validation report is invalid JSON: {error}"]
    if not isinstance(report, dict):
        return ["validation report must contain a JSON object"]
    failures = []
    if report.get("passed") is not True:
        failures.append("validation report does not record a passing validation")
    metadata = report.get("metadata")
    if not isinstance(metadata, dict) or metadata.get("spec") != manifest_spec:
        failures.append("validation report spec does not match manifest spec")
    return failures


def _is_regular_file(path: Path) -> bool:
    return path.is_file() and not path.is_symlink()


def _is_package_filename(value: object) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and Path(value).name == value
        and value not in {".", ".."}
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
