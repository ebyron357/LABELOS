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

_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")


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
    spec_payload = _spec_payload(spec, artwork_destination.name)
    spec_path.write_text(json.dumps(spec_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report_path = destination / "validation-report.json"
    packaged_report = report.to_dict()
    packaged_report["source"] = str(artwork_destination)
    report_path.write_text(json.dumps(packaged_report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "artwork": {
            "file": artwork_destination.name,
            "sha256": _sha256(artwork_destination),
            "bytes": artwork_destination.stat().st_size,
        },
        "label_spec": _manifest_entry(spec_path),
        "validation_report": {
            "file": report_path.name,
            "sha256": _sha256(report_path),
            "bytes": report_path.stat().st_size,
            "passed": report.passed,
        },
        "spec": spec_payload,
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
    except json.JSONDecodeError as error:
        return [f"manifest.json is invalid JSON: {error}"]

    failures: list[str] = []
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        failures.append("manifest schema_version must be 1")
        return failures

    entries: dict[str, Path] = {}
    for key in ("artwork", "label_spec", "validation_report"):
        entry = manifest.get(key)
        if not isinstance(entry, dict):
            failures.append(f"{key} manifest entry is missing or invalid")
            continue
        filename = entry.get("file")
        if not isinstance(filename, str) or not _safe_filename(filename):
            failures.append(f"{key} file name is invalid")
            continue
        if not isinstance(entry.get("sha256"), str) or not _SHA256_RE.fullmatch(entry["sha256"]):
            failures.append(f"{key} sha256 is invalid")
            continue
        if not isinstance(entry.get("bytes"), int) or entry["bytes"] < 0:
            failures.append(f"{key} byte count is invalid")
            continue
        path = destination / filename
        if not path.is_file() or path.is_symlink():
            failures.append(f"{key} file is missing: {filename}")
            continue
        entries[key] = path
        if entry["bytes"] != path.stat().st_size:
            failures.append(f"{key} byte count mismatch: {filename}")
        if entry["sha256"] != _sha256(path):
            failures.append(f"{key} checksum mismatch: {filename}")

    report = _load_json(entries.get("validation_report"), "validation report", failures)
    packaged_spec = _load_json(entries.get("label_spec"), "label spec", failures)
    manifest_spec = manifest.get("spec")
    if isinstance(report, dict) and report.get("passed") is not True:
        failures.append("validation report does not record a passing validation")
    if not isinstance(manifest_spec, dict):
        failures.append("manifest spec is missing or invalid")
    elif packaged_spec is not None and manifest_spec != packaged_spec:
        failures.append("manifest spec does not match label spec")
    if isinstance(report, dict) and isinstance(packaged_spec, dict):
        expected_metadata = _report_spec_metadata(packaged_spec)
        if report.get("metadata", {}).get("spec") != expected_metadata:
            failures.append("validation report spec does not match label spec")
        if "artwork" in entries and report.get("source") != str(entries["artwork"]):
            failures.append("validation report source does not match packaged artwork")
    return failures


def _manifest_entry(path: Path) -> dict[str, str | int]:
    return {"file": path.name, "sha256": _sha256(path), "bytes": path.stat().st_size}


def _spec_payload(spec: LabelSpec, artwork_filename: str) -> dict[str, Any]:
    return {
        "artwork": artwork_filename,
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


def _report_spec_metadata(spec: dict[str, Any]) -> dict[str, Any]:
    return {
        key: spec[key]
        for key in ("width_mm", "height_mm", "bleed_mm", "trim_mm", "safe_area_mm", "min_dpi")
    }


def _safe_filename(filename: str) -> bool:
    return Path(filename).name == filename and filename not in {".", ".."}


def _load_json(path: Path | None, label: str, failures: list[str]) -> Any:
    if path is None:
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        failures.append(f"{label} is invalid JSON: {error}")
        return None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
