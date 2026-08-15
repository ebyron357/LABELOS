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
PACKAGE_ENTRIES = ("artwork", "label_spec", "validation_report")
PACKAGE_FILES = frozenset({"manifest.json", "label-spec.json", "validation-report.json"})


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
    spec_path.write_text(
        json.dumps(_package_spec(spec, artwork_destination.name), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    report_path = destination / "validation-report.json"
    report_path.write_text(json.dumps(report.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "artwork": _manifest_entry(artwork_destination),
        "label_spec": _manifest_entry(spec_path),
        "validation_report": _manifest_entry(report_path),
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
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        return [f"manifest.json is invalid JSON: {error}"]

    if not isinstance(manifest, dict):
        return ["manifest.json root must be an object"]
    if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        return [f"unsupported manifest schema version: {manifest.get('schema_version')!r}"]

    failures: list[str] = []
    entries: dict[str, dict[str, Any]] = {}
    for key in PACKAGE_ENTRIES:
        entry = manifest.get(key)
        if not isinstance(entry, dict):
            failures.append(f"{key} manifest entry is missing or invalid")
        else:
            entries[key] = entry

    filenames = [entry.get("file") for entry in entries.values()]
    safe_filenames = [filename for filename in filenames if _safe_filename(filename)]
    if len(safe_filenames) != len(set(safe_filenames)):
        failures.append("manifest entries must reference distinct files")

    for key, entry in entries.items():
        filename = entry.get("file")
        if not _safe_filename(filename):
            failures.append(f"{key} manifest file is unsafe")
            continue
        checksum = entry.get("sha256")
        if not isinstance(checksum, str) or len(checksum) != 64 or any(
            character not in "0123456789abcdef" for character in checksum
        ):
            failures.append(f"{key} manifest checksum is invalid: {filename}")
            continue
        byte_count = entry.get("bytes")
        if isinstance(byte_count, bool) or not isinstance(byte_count, int) or byte_count < 0:
            failures.append(f"{key} manifest byte count is invalid: {filename}")
            continue
        path = destination / filename
        if not _is_regular_file(path):
            failures.append(f"{key} file is missing or unsafe: {filename}")
        elif path.stat().st_size != byte_count:
            failures.append(f"{key} byte count mismatch: {filename}")
        elif checksum != _sha256(path):
            failures.append(f"{key} checksum mismatch: {filename}")

    if entries.get("label_spec", {}).get("file") != "label-spec.json":
        failures.append("label_spec must be label-spec.json")
    if entries.get("validation_report", {}).get("file") != "validation-report.json":
        failures.append("validation_report must be validation-report.json")

    if not failures:
        failures.extend(_verify_semantic_bindings(destination, entries))

    expected_files = PACKAGE_FILES | {
        entry["file"] for entry in entries.values() if _safe_filename(entry.get("file"))
    }
    actual_files = {path.name for path in destination.iterdir()} if destination.is_dir() else set()
    unexpected_files = sorted(actual_files - expected_files)
    if unexpected_files:
        failures.append(f"unexpected package files: {', '.join(unexpected_files)}")
    return failures


def _verify_semantic_bindings(destination: Path, entries: dict[str, dict[str, Any]]) -> list[str]:
    """Verify package payloads agree with the manifest's artwork binding."""
    try:
        spec = json.loads((destination / "label-spec.json").read_text(encoding="utf-8"))
        report = json.loads((destination / "validation-report.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        return [f"package payload is invalid JSON: {error}"]
    failures: list[str] = []
    if not isinstance(spec, dict) or spec.get("artwork") != entries["artwork"]["file"]:
        failures.append("label-spec.json artwork does not match packaged artwork")
    if not isinstance(report, dict) or report.get("passed") is not True:
        failures.append("validation-report.json does not record a passing validation")
    return failures


def _package_spec(spec: LabelSpec, artwork_filename: str) -> dict[str, object]:
    """Return the canonical package-local label specification."""
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


def _manifest_entry(path: Path) -> dict[str, str | int]:
    return {"file": path.name, "sha256": _sha256(path), "bytes": path.stat().st_size}


def _safe_filename(value: object) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and value not in {".", ".."}
        and "/" not in value
        and "\\" not in value
        and Path(value).name == value
    )


def _is_regular_file(path: Path) -> bool:
    return path.is_file() and not path.is_symlink()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
