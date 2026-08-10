"""Create traceable production release packages from passing validation reports."""

from __future__ import annotations

import hashlib
import json
import shutil
import string
from datetime import datetime, timezone
from pathlib import Path

from .models import LabelSpec, Report

MANIFEST_SCHEMA_VERSION = 1
_RESERVED_PACKAGE_FILENAMES = {"manifest.json", "validation-report.json", "label-spec.json"}


def create_package(spec: LabelSpec, report: Report, destination: Path) -> Path:
    """Create an immutable-style package directory and return its manifest path."""
    if not report.passed:
        raise ValueError("Refusing to package artwork with validation errors")
    if spec.artwork.name in _RESERVED_PACKAGE_FILENAMES:
        raise ValueError(f"Artwork filename is reserved for package metadata: {spec.artwork.name}")
    destination = destination.resolve()
    if destination.exists():
        raise FileExistsError(f"Package destination already exists: {destination}")
    destination.mkdir(parents=True)
    artwork_destination = destination / spec.artwork.name
    shutil.copy2(spec.artwork, artwork_destination)
    report_path = destination / "validation-report.json"
    report_path.write_text(json.dumps(report.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    spec_path = destination / "label-spec.json"
    package_spec = {
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
    spec_path.write_text(json.dumps(package_spec, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
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
    destination = destination.resolve()
    manifest_path = destination / "manifest.json"
    if not manifest_path.is_file():
        return ["manifest.json is missing"]
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return [f"manifest.json is invalid JSON: {error}"]
    if not isinstance(manifest, dict):
        return ["manifest.json must contain an object"]
    if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        return [f"unsupported manifest schema version: {manifest.get('schema_version')!r}"]

    failures = []
    entries: dict[str, Path] = {}
    for key in ("artwork", "validation_report", "label_spec"):
        path, entry_failures = _verify_manifest_entry(destination, key, manifest.get(key))
        failures.extend(entry_failures)
        if path is not None:
            entries[key] = path

    report_entry = manifest.get("validation_report")
    if not isinstance(report_entry, dict) or report_entry.get("passed") is not True:
        failures.append("validation_report manifest entry must record a passing report")
    report = _load_json_object(entries.get("validation_report"))
    if report is None:
        failures.append("validation_report is not valid JSON")
    elif report.get("passed") is not True:
        failures.append("validation_report does not record a passing validation")

    spec = _load_json_object(entries.get("label_spec"))
    artwork_entry = manifest.get("artwork")
    if spec is None:
        failures.append("label_spec is not valid JSON")
    elif not isinstance(artwork_entry, dict) or spec.get("artwork") != artwork_entry.get("file"):
        failures.append("label_spec artwork does not match packaged artwork")
    return failures


def _manifest_entry(path: Path) -> dict[str, str | int]:
    return {"file": path.name, "sha256": _sha256(path), "bytes": path.stat().st_size}


def _verify_manifest_entry(
    destination: Path, key: str, entry: object
) -> tuple[Path | None, list[str]]:
    if not isinstance(entry, dict):
        return None, [f"{key} manifest entry is invalid"]
    filename = entry.get("file")
    if not isinstance(filename, str) or not _is_safe_package_filename(filename):
        return None, [f"{key} manifest filename is unsafe"]
    if (
        not isinstance(entry.get("sha256"), str)
        or len(entry["sha256"]) != 64
        or any(character not in string.hexdigits for character in entry["sha256"])
    ):
        return None, [f"{key} manifest checksum is invalid"]
    if not isinstance(entry.get("bytes"), int) or entry["bytes"] < 0:
        return None, [f"{key} manifest byte count is invalid"]
    path = (destination / filename).resolve()
    if destination not in path.parents or not path.is_file():
        return None, [f"{key} file is missing: {filename}"]
    failures = []
    if entry["bytes"] != path.stat().st_size:
        failures.append(f"{key} byte count mismatch: {filename}")
    if entry["sha256"] != _sha256(path):
        failures.append(f"{key} checksum mismatch: {filename}")
    return path, failures


def _is_safe_package_filename(filename: str) -> bool:
    path = Path(filename)
    return filename not in {"", ".", ".."} and path.name == filename and not path.is_absolute()


def _load_json_object(path: Path | None) -> dict[str, object] | None:
    if path is None:
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
