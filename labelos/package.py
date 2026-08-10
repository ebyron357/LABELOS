"""Create traceable production release packages from passing validation reports."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

from .models import LabelSpec, Report

MANIFEST_SCHEMA_VERSION = 1
SHA256_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")


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
    package_spec = _package_spec(spec, artwork_destination.name)
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
    if not manifest_path.is_file():
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

    verified: dict[str, Path] = {}
    for key in ("artwork", "label_spec", "validation_report"):
        path = _verify_entry(destination, key, manifest.get(key), failures)
        if path is not None:
            verified[key] = path

    report_entry = manifest.get("validation_report")
    if not isinstance(report_entry, dict) or report_entry.get("passed") is not True:
        failures.append("validation report is not marked as passing")
    report = _read_json(verified.get("validation_report"), "validation report", failures)
    label_spec = _read_json(verified.get("label_spec"), "label spec", failures)
    if isinstance(label_spec, dict) and isinstance(manifest.get("artwork"), dict):
        if label_spec.get("artwork") != manifest["artwork"].get("file"):
            failures.append("label spec artwork does not match manifest artwork")
    else:
        label_spec = None
    if isinstance(label_spec, dict) and label_spec != manifest.get("spec"):
        failures.append("label spec does not match manifest spec")
    if isinstance(report, dict):
        if report.get("passed") is not True:
            failures.append("validation report does not pass")
        report_spec = report.get("metadata", {}).get("spec") if isinstance(report.get("metadata"), dict) else None
        if isinstance(report_spec, dict) and isinstance(label_spec, dict):
            for key in ("width_mm", "height_mm", "bleed_mm", "trim_mm", "safe_area_mm", "min_dpi"):
                if report_spec.get(key) != label_spec.get(key):
                    failures.append(f"validation report spec does not match label spec: {key}")
    return failures


def _package_spec(spec: LabelSpec, artwork_file: str) -> dict[str, object]:
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


def _manifest_entry(path: Path) -> dict[str, str | int]:
    return {"file": path.name, "sha256": _sha256(path), "bytes": path.stat().st_size}


def _verify_entry(
    destination: Path, key: str, entry: object, failures: list[str]
) -> Path | None:
    if not isinstance(entry, dict):
        failures.append(f"{key} entry is missing or invalid")
        return None
    filename = entry.get("file")
    if not _safe_filename(filename):
        failures.append(f"{key} has an unsafe package filename")
        return None
    path = destination / filename
    if not path.is_file():
        failures.append(f"{key} file is missing: {filename}")
        return None
    checksum = entry.get("sha256")
    if not isinstance(checksum, str) or not SHA256_PATTERN.fullmatch(checksum):
        failures.append(f"{key} has an invalid SHA-256 checksum")
    elif checksum.lower() != _sha256(path):
        failures.append(f"{key} checksum mismatch: {filename}")
    byte_count = entry.get("bytes")
    if isinstance(byte_count, bool) or not isinstance(byte_count, int) or byte_count < 0:
        failures.append(f"{key} has an invalid byte count")
    elif byte_count != path.stat().st_size:
        failures.append(f"{key} byte count mismatch: {filename}")
    return path


def _safe_filename(value: object) -> bool:
    return isinstance(value, str) and value not in {"", ".", ".."} and Path(value).name == value


def _read_json(path: Path | None, name: str, failures: list[str]) -> object | None:
    if path is None:
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        failures.append(f"{name} is invalid JSON: {error}")
        return None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
