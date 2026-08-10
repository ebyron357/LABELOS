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
    destination.mkdir(parents=True)
    artwork_destination = destination / spec.artwork.name
    shutil.copy2(spec.artwork, artwork_destination)
    spec_path = destination / "label-spec.json"
    package_spec = {
        "schema_version": 1,
        "artwork": artwork_destination.name,
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
    spec_path.write_text(json.dumps(package_spec, indent=2, sort_keys=True) + "\n", encoding="utf-8")
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
            "bytes": report_path.stat().st_size,
            "passed": report.passed,
        },
        "label_spec": {
            "file": spec_path.name,
            "sha256": _sha256(spec_path),
            "bytes": spec_path.stat().st_size,
        },
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
    failures: list[str] = []
    if manifest.get("schema_version") != 1:
        failures.append("manifest schema_version must be 1")
    entries = {
        "artwork": None,
        "validation_report": "validation-report.json",
        "label_spec": "label-spec.json",
    }
    for key, expected_filename in entries.items():
        entry = manifest.get(key)
        if not isinstance(entry, dict):
            failures.append(f"{key} manifest entry is missing or invalid")
            continue
        filename = entry.get("file")
        if not isinstance(filename, str) or Path(filename).name != filename:
            failures.append(f"{key} file must be a package-local filename")
            continue
        if expected_filename is not None and filename != expected_filename:
            failures.append(f"{key} file must be named {expected_filename}")
            continue
        path = destination / filename
        if not path.is_file() or path.is_symlink():
            failures.append(f"{key} file is missing or is not a regular file: {filename}")
            continue
        digest = entry.get("sha256")
        if not isinstance(digest, str) or not _is_sha256(digest):
            failures.append(f"{key} checksum is not a lowercase SHA-256 digest: {filename}")
        elif digest != _sha256(path):
            failures.append(f"{key} checksum mismatch: {filename}")
        if entry.get("bytes") != path.stat().st_size:
            failures.append(f"{key} byte count mismatch: {filename}")

    report = _read_json(destination / "validation-report.json", "validation report", failures)
    label_spec = _read_json(destination / "label-spec.json", "label spec", failures)
    if report is not None and report.get("passed") is not True:
        failures.append("validation report does not record a passing validation")
    if label_spec is not None:
        if label_spec.get("schema_version") != 1:
            failures.append("label spec schema_version must be 1")
        artwork = manifest.get("artwork", {})
        if label_spec.get("artwork") != artwork.get("file"):
            failures.append("label spec artwork does not match manifest artwork")
    return failures


def _read_json(path: Path, description: str, failures: list[str]) -> dict | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        failures.append(f"{description} is invalid JSON: {error}")
        return None
    if not isinstance(value, dict):
        failures.append(f"{description} root must be a JSON object")
        return None
    return value


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
