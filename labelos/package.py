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
REPORT_FILE = "validation-report.json"
SPEC_FILE = "label-spec.json"
MANIFEST_FILE = "manifest.json"


def create_package(spec: LabelSpec, report: Report, destination: Path) -> Path:
    """Create an immutable-style package directory and return its manifest path."""
    if not report.passed:
        raise ValueError("Refusing to package artwork with validation errors")
    destination = destination.resolve()
    if destination.exists():
        raise FileExistsError(f"Package destination already exists: {destination}")
    destination.mkdir(parents=True)
    artwork_destination = destination / spec.artwork.name
    reserved_files = {REPORT_FILE, SPEC_FILE, MANIFEST_FILE}
    if artwork_destination.name in reserved_files:
        raise ValueError(f"Artwork filename is reserved for package metadata: {artwork_destination.name}")
    shutil.copy2(spec.artwork, artwork_destination)
    spec_path = destination / SPEC_FILE
    spec_path.write_text(json.dumps(_package_spec(spec), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report_path = destination / REPORT_FILE
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
            "file": REPORT_FILE,
            "sha256": _sha256(report_path),
            "bytes": report_path.stat().st_size,
            "passed": report.passed,
        },
        "label_spec": {
            "file": SPEC_FILE,
            "sha256": _sha256(spec_path),
            "bytes": spec_path.stat().st_size,
        },
    }
    manifest_path = destination / MANIFEST_FILE
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest_path


def verify_package(destination: Path) -> list[str]:
    """Return integrity failures for a release package."""
    destination = destination.resolve()
    manifest_path = destination / MANIFEST_FILE
    if not manifest_path.is_file() or manifest_path.is_symlink():
        return ["manifest.json is missing"]
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        return [f"manifest.json is invalid JSON: {error}"]
    if not isinstance(manifest, dict):
        return ["manifest.json root must be an object"]
    if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        return [f"unsupported manifest schema version: {manifest.get('schema_version')!r}"]

    failures: list[str] = []
    entries = {
        "artwork": manifest.get("artwork"),
        "validation_report": manifest.get("validation_report"),
        "label_spec": manifest.get("label_spec"),
    }
    expected_files: set[str] = {MANIFEST_FILE}
    for key, entry in entries.items():
        path = _validated_entry_path(destination, key, entry, failures)
        if path is None:
            continue
        expected_files.add(path.name)
        _verify_entry(key, path, entry, failures)

    actual_files = {item.name for item in destination.iterdir()}
    unexpected = sorted(actual_files - expected_files)
    if unexpected:
        failures.append(f"unexpected package files: {', '.join(unexpected)}")
    if actual_files != expected_files:
        missing = sorted(expected_files - actual_files)
        if missing:
            failures.append(f"package files are missing: {', '.join(missing)}")

    report_path = _entry_file(destination, entries["validation_report"])
    spec_path = _entry_file(destination, entries["label_spec"])
    artwork_path = _entry_file(destination, entries["artwork"])
    if report_path and spec_path and artwork_path and not failures:
        _verify_package_relationships(report_path, spec_path, artwork_path, failures)
    return failures


def _package_spec(spec: LabelSpec) -> dict[str, Any]:
    return {
        "artwork": spec.artwork.name,
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


def _validated_entry_path(
    destination: Path, key: str, entry: Any, failures: list[str]
) -> Path | None:
    if not isinstance(entry, dict):
        failures.append(f"{key} manifest entry is invalid")
        return None
    filename = entry.get("file")
    if not isinstance(filename, str) or Path(filename).name != filename or filename in {"", ".", ".."}:
        failures.append(f"{key} file path is unsafe")
        return None
    required_names = {"validation_report": REPORT_FILE, "label_spec": SPEC_FILE}
    if key in required_names and filename != required_names[key]:
        failures.append(f"{key} file name is invalid: {filename}")
        return None
    if key == "artwork" and filename in {REPORT_FILE, SPEC_FILE, MANIFEST_FILE}:
        failures.append(f"{key} file name is reserved: {filename}")
        return None
    return destination / filename


def _entry_file(destination: Path, entry: Any) -> Path | None:
    if not isinstance(entry, dict) or not isinstance(entry.get("file"), str):
        return None
    filename = entry["file"]
    if Path(filename).name != filename or filename in {"", ".", ".."}:
        return None
    return destination / filename


def _verify_entry(key: str, path: Path, entry: Any, failures: list[str]) -> None:
    if not path.is_file() or path.is_symlink():
        failures.append(f"{key} file is missing or is not a regular file: {path.name}")
        return
    if not isinstance(entry.get("bytes"), int) or entry["bytes"] < 0:
        failures.append(f"{key} byte count is invalid: {path.name}")
    elif entry["bytes"] != path.stat().st_size:
        failures.append(f"{key} byte count mismatch: {path.name}")
    expected_hash = entry.get("sha256")
    if not isinstance(expected_hash, str) or len(expected_hash) != 64:
        failures.append(f"{key} checksum is invalid: {path.name}")
    elif expected_hash != _sha256(path):
        failures.append(f"{key} checksum mismatch: {path.name}")


def _verify_package_relationships(
    report_path: Path, spec_path: Path, artwork_path: Path, failures: list[str]
) -> None:
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        failures.append(f"package metadata is invalid JSON: {error}")
        return
    if not isinstance(report, dict) or report.get("passed") is not True:
        failures.append("validation report does not record a passing result")
    if not isinstance(spec, dict) or spec.get("artwork") != artwork_path.name:
        failures.append("label spec artwork does not match packaged artwork")
    report_source = report.get("source") if isinstance(report, dict) else None
    if not isinstance(report_source, str) or Path(report_source).name != artwork_path.name:
        failures.append("validation report source does not match packaged artwork")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
