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
    spec_path = destination / "label-spec.json"
    package_spec = _package_spec(spec)
    spec_path.write_text(json.dumps(package_spec, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report_path = destination / "validation-report.json"
    report_document = report.to_dict()
    report_document["metadata"]["spec"] = package_spec
    report_path.write_text(json.dumps(report_document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "artwork": {
            "file": artwork_destination.name,
            "sha256": _sha256(artwork_destination),
            "bytes": artwork_destination.stat().st_size,
        },
        "label_spec": {
            "file": spec_path.name,
            "sha256": _sha256(spec_path),
            "bytes": spec_path.stat().st_size,
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
        return ["manifest.json root must be an object"]

    failures: list[str] = []
    if manifest.get("schema_version") != 1:
        failures.append("manifest schema_version must be 1")
    entries: dict[str, Path] = {}
    for key in ("artwork", "label_spec", "validation_report"):
        path = _verify_entry(destination, key, manifest.get(key), failures)
        if path is not None:
            entries[key] = path

    report = _read_json(entries.get("validation_report"), "validation report", failures)
    package_spec = _read_json(entries.get("label_spec"), "label spec", failures)
    if isinstance(report, dict) and report.get("passed") is not True:
        failures.append("validation report does not record a passing result")
    if isinstance(package_spec, dict):
        if manifest.get("spec") != package_spec:
            failures.append("manifest spec does not match label spec")
        metadata = report.get("metadata") if isinstance(report, dict) else None
        if not isinstance(metadata, dict) or metadata.get("spec") != package_spec:
            failures.append("validation report spec does not match label spec")
    return failures


def _package_spec(spec: LabelSpec) -> dict[str, Any]:
    return {
        "artwork": spec.artwork.name,
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


def _verify_entry(
    destination: Path, key: str, entry: object, failures: list[str]
) -> Path | None:
    if not isinstance(entry, dict):
        failures.append(f"{key} manifest entry is invalid")
        return None
    filename = entry.get("file")
    if not isinstance(filename, str) or Path(filename).name != filename or filename in {".", ".."}:
        failures.append(f"{key} file name is invalid")
        return None
    path = destination / filename
    if not _is_regular_file(path):
        failures.append(f"{key} file is missing or not a regular file: {filename}")
        return None
    expected_bytes = entry.get("bytes")
    if not isinstance(expected_bytes, int) or isinstance(expected_bytes, bool) or expected_bytes < 0:
        failures.append(f"{key} byte count is invalid: {filename}")
    elif path.stat().st_size != expected_bytes:
        failures.append(f"{key} byte count mismatch: {filename}")
    expected_digest = entry.get("sha256")
    if not isinstance(expected_digest, str) or not _SHA256_PATTERN.fullmatch(expected_digest):
        failures.append(f"{key} checksum is invalid: {filename}")
    elif expected_digest != _sha256(path):
        failures.append(f"{key} checksum mismatch: {filename}")
    return path


def _read_json(path: Path | None, name: str, failures: list[str]) -> object | None:
    if path is None:
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        failures.append(f"{name} is invalid JSON: {error}")
        return None


def _is_regular_file(path: Path) -> bool:
    return path.is_file() and not path.is_symlink()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
