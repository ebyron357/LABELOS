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
    if spec.artwork.name in {"manifest.json", "label-spec.json", "validation-report.json"}:
        raise ValueError("Artwork filename conflicts with a reserved package filename")
    destination.mkdir(parents=True)
    artwork_destination = destination / spec.artwork.name
    shutil.copy2(spec.artwork, artwork_destination)
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
    report_path = destination / "validation-report.json"
    report_path.write_text(json.dumps(report.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest = {
        "schema_version": 2,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "files": {
            "artwork": _file_entry(artwork_destination),
            "label_spec": _file_entry(spec_path),
            "validation_report": _file_entry(report_path),
        },
    }
    manifest_path = destination / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest_path


def verify_package(destination: Path) -> list[str]:
    """Return integrity failures for a release package."""
    destination = destination.resolve()
    manifest_path = destination / "manifest.json"
    if not manifest_path.is_file() or manifest_path.is_symlink():
        return ["manifest.json is missing"]
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        return [f"manifest.json is invalid JSON: {error}"]
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 2:
        return ["manifest.json has an unsupported schema_version"]
    files = manifest.get("files")
    expected_keys = {"artwork", "label_spec", "validation_report"}
    if not isinstance(files, dict) or set(files) != expected_keys:
        return ["manifest.json must contain exactly the required file entries"]

    failures: list[str] = []
    package_files = {"manifest.json"}
    entries: dict[str, Path] = {}
    for key in sorted(expected_keys):
        entry = files[key]
        if not isinstance(entry, dict):
            failures.append(f"{key} manifest entry is invalid")
            continue
        filename = entry.get("file")
        if not isinstance(filename, str) or not _is_safe_filename(filename):
            failures.append(f"{key} has an unsafe filename")
            continue
        path = destination / filename
        package_files.add(filename)
        entries[key] = path
        if not path.exists() or not path.is_file() or path.is_symlink():
            failures.append(f"{key} file is missing or is not a regular file: {filename}")
            continue
        if entry.get("bytes") != path.stat().st_size:
            failures.append(f"{key} byte count mismatch: {filename}")
        if entry.get("sha256") != _sha256(path):
            failures.append(f"{key} checksum mismatch: {filename}")
    filenames = [path.name for path in entries.values()]
    if len(filenames) != len(set(filenames)):
        failures.append("manifest.json contains duplicate file entries")
    actual_files = {
        child.name
        for child in destination.iterdir()
        if child.is_file() and not child.is_symlink()
    }
    unexpected = sorted(actual_files - package_files)
    if unexpected:
        failures.append(f"unexpected package files: {', '.join(unexpected)}")
    non_regular = sorted(child.name for child in destination.iterdir() if not child.is_file() or child.is_symlink())
    if non_regular:
        failures.append(f"package contains non-regular artifacts: {', '.join(non_regular)}")
    if failures:
        return failures

    try:
        spec = json.loads(entries["label_spec"].read_text(encoding="utf-8"))
        report = json.loads(entries["validation_report"].read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        return [f"package JSON is invalid: {error}"]
    if not isinstance(spec, dict) or spec.get("artwork") != entries["artwork"].name:
        return ["label-spec.json does not bind to the packaged artwork"]
    if not isinstance(report, dict) or report.get("passed") is not True:
        return ["validation-report.json does not record a passing validation"]
    return failures


def _file_entry(path: Path) -> dict[str, str | int]:
    return {"file": path.name, "sha256": _sha256(path), "bytes": path.stat().st_size}


def _is_safe_filename(filename: str) -> bool:
    return Path(filename).name == filename and filename not in {"", ".", ".."}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
