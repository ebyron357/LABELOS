"""Create traceable production release packages from passing validation reports."""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from .models import LabelSpec, Report

PACKAGE_SCHEMA_VERSION = 1
_DIGEST_LENGTH = 64


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
    spec_path = destination / "label-spec.json"
    package_spec = _package_spec(spec, artwork_destination.name)
    spec_path.write_text(json.dumps(package_spec, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest = {
        "schema_version": PACKAGE_SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "artwork": _file_entry(artwork_destination),
        "label_spec": _file_entry(spec_path),
        "validation_report": {**_file_entry(report_path), "passed": report.passed},
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
    if manifest_path.is_symlink():
        return ["manifest.json is not a regular file"]
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        return [f"manifest.json is invalid JSON: {error}"]
    if not isinstance(manifest, dict):
        return ["manifest.json root must be an object"]
    if manifest.get("schema_version") != PACKAGE_SCHEMA_VERSION:
        return [f"unsupported package schema version: {manifest.get('schema_version')!r}"]
    failures = []
    entries: dict[str, Path] = {}
    for key in ("artwork", "label_spec", "validation_report"):
        path, entry_failures = _verify_file_entry(destination, key, manifest.get(key))
        failures.extend(entry_failures)
        if path is not None:
            entries[key] = path
    if failures:
        return failures
    try:
        report = json.loads(entries["validation_report"].read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        return [f"validation_report is invalid JSON: {error}"]
    if not isinstance(report, dict) or report.get("passed") is not True:
        failures.append("validation_report does not record a passing validation")
    if manifest["validation_report"].get("passed") is not True:
        failures.append("manifest does not record a passing validation report")
    report_metadata = report.get("metadata") if isinstance(report, dict) else None
    if not isinstance(report_metadata, dict) or report_metadata.get("spec") != manifest.get("spec"):
        failures.append("validation_report spec does not match manifest spec")
    try:
        package_spec = json.loads(entries["label_spec"].read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        return [f"label_spec is invalid JSON: {error}"]
    if not isinstance(package_spec, dict):
        failures.append("label_spec root must be an object")
    elif package_spec.get("artwork") != entries["artwork"].name:
        failures.append("label_spec artwork does not match packaged artwork")
    elif _report_spec(package_spec) != manifest.get("spec"):
        failures.append("label_spec dimensions do not match manifest spec")
    return failures


def _package_spec(spec: LabelSpec, artwork_file: str) -> dict:
    return {
        "artwork": artwork_file,
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


def _report_spec(package_spec: dict) -> dict:
    return {
        key: package_spec[key]
        for key in ("width_mm", "height_mm", "bleed_mm", "trim_mm", "safe_area_mm", "min_dpi")
        if key in package_spec
    }


def _file_entry(path: Path) -> dict:
    return {"file": path.name, "sha256": _sha256(path), "bytes": path.stat().st_size}


def _verify_file_entry(destination: Path, key: str, entry: object) -> tuple[Path | None, list[str]]:
    if not isinstance(entry, dict):
        return None, [f"{key} entry is missing or invalid"]
    filename = entry.get("file")
    if not isinstance(filename, str) or not filename or Path(filename).name != filename:
        return None, [f"{key} file name is invalid"]
    if not _is_sha256(entry.get("sha256")):
        return None, [f"{key} checksum is invalid"]
    if not isinstance(entry.get("bytes"), int) or isinstance(entry["bytes"], bool) or entry["bytes"] < 0:
        return None, [f"{key} byte count is invalid"]
    path = destination / filename
    if path.is_symlink() or not path.is_file():
        return None, [f"{key} file is missing or not a regular file: {filename}"]
    failures = []
    if entry["bytes"] != path.stat().st_size:
        failures.append(f"{key} byte count mismatch: {filename}")
    if entry["sha256"] != _sha256(path):
        failures.append(f"{key} checksum mismatch: {filename}")
    return path, failures


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == _DIGEST_LENGTH
        and all(character in "0123456789abcdef" for character in value)
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
