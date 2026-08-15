"""Create traceable production release packages from passing validation reports."""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import LabelSpec, Report

MANIFEST_SCHEMA_VERSION = 2
_REPORT_FILE = "validation-report.json"
_SPEC_FILE = "label-spec.json"


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
    report_path = destination / _REPORT_FILE
    report_path.write_text(json.dumps(report.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    spec_path = destination / _SPEC_FILE
    package_spec = _package_spec(spec, artwork_destination.name)
    spec_path.write_text(json.dumps(package_spec, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "artwork": _file_entry(artwork_destination),
        "label_spec": _file_entry(spec_path),
        "validation_report": {**_file_entry(report_path), "passed": report.passed},
    }
    manifest_path = destination / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest_path


def verify_package(destination: Path) -> list[str]:
    """Return structural and integrity failures for a release package."""
    manifest_path = destination / "manifest.json"
    if not manifest_path.is_file() or manifest_path.is_symlink():
        return ["manifest.json is missing or not a regular file"]
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        return [f"manifest.json is invalid JSON: {error}"]
    if not isinstance(manifest, dict):
        return ["manifest.json root must be an object"]
    if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        return [f"unsupported manifest schema version: {manifest.get('schema_version')!r}"]

    failures: list[str] = []
    entries = {
        "artwork": manifest.get("artwork"),
        "label_spec": manifest.get("label_spec"),
        "validation_report": manifest.get("validation_report"),
    }
    fixed_filenames = {"label_spec": _SPEC_FILE, "validation_report": _REPORT_FILE}
    paths: dict[str, Path] = {}
    for key, entry in entries.items():
        path = _verified_entry_path(destination, key, entry, failures)
        if path is not None:
            if key in fixed_filenames and path.name != fixed_filenames[key]:
                failures.append(f"{key} file name is invalid: {path.name}")
            paths[key] = path
    if len({path.name for path in paths.values()}) != len(paths):
        failures.append("manifest file entries must name distinct files")

    expected_files = {"manifest.json"} | {path.name for path in paths.values()}
    if destination.is_dir():
        actual_files = {path.name for path in destination.iterdir()}
        for unexpected in sorted(actual_files - expected_files):
            failures.append(f"unexpected package file: {unexpected}")

    if set(paths) == set(entries):
        _verify_package_content(paths, failures)
    return failures


def _package_spec(spec: LabelSpec, artwork_file: str) -> dict[str, Any]:
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


def _file_entry(path: Path) -> dict[str, str | int]:
    return {"file": path.name, "sha256": _sha256(path), "bytes": path.stat().st_size}


def _verified_entry_path(
    destination: Path, key: str, entry: Any, failures: list[str]
) -> Path | None:
    if not isinstance(entry, dict):
        failures.append(f"{key} manifest entry is invalid")
        return None
    filename = entry.get("file")
    if not isinstance(filename, str) or Path(filename).name != filename or filename in {"", ".", ".."}:
        failures.append(f"{key} file path is unsafe")
        return None
    path = destination / filename
    if not path.is_file() or path.is_symlink():
        failures.append(f"{key} file is missing or not a regular file: {filename}")
        return None
    if entry.get("bytes") != path.stat().st_size:
        failures.append(f"{key} byte count mismatch: {filename}")
    if not isinstance(entry.get("sha256"), str) or entry["sha256"] != _sha256(path):
        failures.append(f"{key} checksum mismatch: {filename}")
    return path


def _verify_package_content(paths: dict[str, Path], failures: list[str]) -> None:
    try:
        package_spec = json.loads(paths["label_spec"].read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        failures.append(f"label_spec is invalid JSON: {error}")
        return
    if not isinstance(package_spec, dict) or package_spec.get("artwork") != paths["artwork"].name:
        failures.append("label_spec artwork binding is invalid")

    try:
        report = json.loads(paths["validation_report"].read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        failures.append(f"validation_report is invalid JSON: {error}")
        return
    if not isinstance(report, dict) or report.get("passed") is not True:
        failures.append("validation_report does not record a passing validation")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
