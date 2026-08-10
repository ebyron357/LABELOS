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
    spec_path = destination / "label-spec.json"
    packaged_spec = {
        "artwork": artwork_destination.name,
        "barcode_value": spec.barcode_value,
        "bleed_mm": spec.bleed_mm,
        "height_mm": spec.height_mm,
        "min_dpi": spec.min_dpi,
        "qr_value": spec.qr_value,
        "required_copy": list(spec.required_copy),
        "safe_area_mm": spec.safe_area_mm,
        "trim_mm": spec.trim_mm,
        "width_mm": spec.width_mm,
    }
    spec_path.write_text(json.dumps(packaged_spec, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "artwork": _manifest_entry(artwork_destination),
        "validation_report": {**_manifest_entry(report_path), "passed": report.passed},
        "label_spec": _manifest_entry(spec_path),
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
        return ["manifest.json must contain a JSON object"]
    if manifest.get("schema_version") != 1:
        return ["unsupported manifest schema version"]

    failures: list[str] = []
    entries: dict[str, Path] = {}
    for key in ("artwork", "validation_report", "label_spec"):
        entry = manifest.get(key)
        error = _validate_manifest_entry(key, entry)
        if error:
            failures.append(error)
            continue
        assert isinstance(entry, dict)
        path = destination / entry["file"]
        entries[key] = path
        if not path.is_file():
            failures.append(f"{key} file is missing: {path.name}")
        elif entry["sha256"] != _sha256(path):
            failures.append(f"{key} checksum mismatch: {path.name}")
        elif entry["bytes"] != path.stat().st_size:
            failures.append(f"{key} byte count mismatch: {path.name}")
    if failures:
        return failures

    try:
        report = json.loads(entries["validation_report"].read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        failures.append("validation_report is invalid JSON")
    else:
        if not isinstance(report, dict) or report.get("passed") is not True:
            failures.append("validation_report does not record a passing validation")
    try:
        packaged_spec = json.loads(entries["label_spec"].read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        failures.append("label_spec is invalid JSON")
    else:
        if not isinstance(packaged_spec, dict) or packaged_spec.get("artwork") != entries["artwork"].name:
            failures.append("label_spec does not reference packaged artwork")
    return failures


def _manifest_entry(path: Path) -> dict[str, str | int]:
    return {"file": path.name, "sha256": _sha256(path), "bytes": path.stat().st_size}


def _validate_manifest_entry(key: str, entry: object) -> str | None:
    if not isinstance(entry, dict):
        return f"{key} manifest entry is invalid"
    file_name, digest, byte_count = entry.get("file"), entry.get("sha256"), entry.get("bytes")
    if not isinstance(file_name, str) or Path(file_name).name != file_name or file_name in {".", ".."}:
        return f"{key} manifest filename is unsafe"
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        return f"{key} manifest checksum is invalid"
    if not isinstance(byte_count, int) or isinstance(byte_count, bool) or byte_count < 0:
        return f"{key} manifest byte count is invalid"
    return None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
