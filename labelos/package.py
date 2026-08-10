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
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


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
    package_spec = _package_spec(spec, artwork_destination.name)
    report.metadata["spec"] = package_spec
    report_path = destination / "validation-report.json"
    _write_json(report_path, report.to_dict())
    spec_path = destination / "label-spec.json"
    _write_json(spec_path, package_spec)
    manifest = {
        "schema_version": PACKAGE_SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "artwork": _manifest_entry(artwork_destination),
        "validation_report": {**_manifest_entry(report_path), "passed": report.passed},
        "label_spec": _manifest_entry(spec_path),
        "spec": package_spec,
    }
    manifest_path = destination / "manifest.json"
    _write_json(manifest_path, manifest)
    return manifest_path


def verify_package(destination: Path) -> list[str]:
    """Return integrity and provenance failures for a release package."""
    manifest_path = destination / "manifest.json"
    if not manifest_path.is_file():
        return ["manifest.json is missing"]
    manifest, errors = _read_json_object(manifest_path, "manifest.json")
    if errors:
        return errors

    failures = _validate_manifest(manifest)
    entries = {
        "artwork": manifest.get("artwork"),
        "validation_report": manifest.get("validation_report"),
        "label_spec": manifest.get("label_spec"),
    }
    expected_files = {"manifest.json"}
    for key, entry in entries.items():
        if not isinstance(entry, dict):
            continue
        filename = entry.get("file")
        if isinstance(filename, str) and _is_local_filename(filename):
            expected_files.add(filename)
            path = destination / filename
            if not path.is_file() or path.is_symlink():
                failures.append(f"{key} file is missing or not a regular file: {filename}")
                continue
            if entry.get("bytes") != path.stat().st_size:
                failures.append(f"{key} byte count mismatch: {filename}")
            if entry.get("sha256") != _sha256(path):
                failures.append(f"{key} checksum mismatch: {filename}")

    actual_files = {path.name for path in destination.iterdir()} if destination.is_dir() else set()
    unexpected = sorted(actual_files - expected_files)
    if unexpected:
        failures.append(f"package contains unexpected files: {', '.join(unexpected)}")
    failures.extend(_verify_report_and_spec(destination, manifest))
    return failures


def _package_spec(spec: LabelSpec, artwork_filename: str) -> dict[str, Any]:
    return {
        "schema_version": PACKAGE_SCHEMA_VERSION,
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


def _manifest_entry(path: Path) -> dict[str, str | int]:
    return {"file": path.name, "sha256": _sha256(path), "bytes": path.stat().st_size}


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _read_json_object(path: Path, label: str) -> tuple[dict[str, Any], list[str]]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return {}, [f"{label} is invalid JSON: {error}"]
    if not isinstance(value, dict):
        return {}, [f"{label} must contain a JSON object"]
    return value, []


def _validate_manifest(manifest: dict[str, Any]) -> list[str]:
    failures = []
    schema_version = manifest.get("schema_version")
    if isinstance(schema_version, bool) or schema_version != PACKAGE_SCHEMA_VERSION:
        failures.append(f"unsupported manifest schema version: {manifest.get('schema_version')!r}")
    for key in ("artwork", "validation_report", "label_spec"):
        entry = manifest.get(key)
        if not isinstance(entry, dict):
            failures.append(f"manifest {key} entry is missing or invalid")
            continue
        filename, digest, byte_count = entry.get("file"), entry.get("sha256"), entry.get("bytes")
        if not isinstance(filename, str) or not _is_local_filename(filename):
            failures.append(f"manifest {key} filename is invalid")
        if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
            failures.append(f"manifest {key} SHA-256 is invalid")
        if isinstance(byte_count, bool) or not isinstance(byte_count, int) or byte_count < 0:
            failures.append(f"manifest {key} byte count is invalid")
    validation_report = manifest.get("validation_report")
    if not isinstance(validation_report, dict) or validation_report.get("passed") is not True:
        failures.append("manifest validation report is not marked as passing")
    return failures


def _verify_report_and_spec(destination: Path, manifest: dict[str, Any]) -> list[str]:
    failures = []
    report_name = _entry_filename(manifest, "validation_report")
    spec_name = _entry_filename(manifest, "label_spec")
    if report_name is None or spec_name is None:
        return failures
    report, report_errors = _read_json_object(destination / report_name, "validation report")
    package_spec, spec_errors = _read_json_object(destination / spec_name, "package label spec")
    failures.extend(report_errors)
    failures.extend(spec_errors)
    if report_errors or spec_errors:
        return failures
    manifest_spec = manifest.get("spec")
    if not isinstance(manifest_spec, dict):
        return failures + ["manifest spec is missing or invalid"]
    if package_spec != manifest_spec:
        failures.append("package label spec does not match manifest spec")
    if report.get("passed") is not True:
        failures.append("validation report is not passing")
    metadata = report.get("metadata")
    if not isinstance(metadata, dict) or metadata.get("spec") != manifest_spec:
        failures.append("validation report spec does not match manifest spec")
    return failures


def _entry_filename(manifest: dict[str, Any], key: str) -> str | None:
    entry = manifest.get(key)
    if not isinstance(entry, dict):
        return None
    filename = entry.get("file")
    return filename if isinstance(filename, str) and _is_local_filename(filename) else None


def _is_local_filename(filename: str) -> bool:
    return (
        filename not in {"", ".", ".."}
        and "/" not in filename
        and "\\" not in filename
        and Path(filename).name == filename
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
