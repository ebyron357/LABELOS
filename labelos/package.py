"""Create traceable production release packages from passing validation reports."""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from .models import LabelSpec, Report

MANIFEST_SCHEMA_VERSION = 1


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
    spec_path.write_text(
        json.dumps(
            {
                "artwork": artwork_destination.name,
                "width_mm": spec.width_mm,
                "height_mm": spec.height_mm,
                "trim_mm": spec.trim_mm,
                "bleed_mm": spec.bleed_mm,
                "safe_area_mm": spec.safe_area_mm,
                "min_dpi": spec.min_dpi,
                "required_copy": list(spec.required_copy),
                "barcode_value": spec.barcode_value,
                "qr_value": spec.qr_value,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
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
    manifest_path = destination / "manifest.json"
    if not manifest_path.is_file():
        return ["manifest.json is missing"]
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        return [f"manifest.json is invalid JSON: {error}"]
    if not isinstance(manifest, dict):
        return ["manifest.json root must be an object"]
    schema_version = manifest.get("schema_version")
    if (
        not isinstance(schema_version, int)
        or isinstance(schema_version, bool)
        or schema_version != MANIFEST_SCHEMA_VERSION
    ):
        return [f"unsupported manifest schema version: {schema_version!r}"]

    failures = []
    for key in ("artwork", "validation_report", "label_spec"):
        entry = manifest.get(key, {})
        if not isinstance(entry, dict):
            failures.append(f"{key} entry must be an object")
            continue
        path, path_error = _package_file(destination, entry.get("file"))
        if path_error:
            failures.append(f"{key} file is invalid: {path_error}")
            continue
        if not path.is_file():
            failures.append(f"{key} file is missing: {path.name}")
            continue
        if entry.get("sha256") != _sha256(path):
            failures.append(f"{key} checksum mismatch: {path.name}")
        if entry.get("bytes") != path.stat().st_size:
            failures.append(f"{key} byte count mismatch: {path.name}")
    validation_report = manifest.get("validation_report")
    if not isinstance(validation_report, dict) or validation_report.get("passed") is not True:
        failures.append("validation_report must record a passing validation result")
    return failures


def _manifest_entry(path: Path) -> dict[str, str | int]:
    return {"file": path.name, "sha256": _sha256(path), "bytes": path.stat().st_size}


def _package_file(destination: Path, name: object) -> tuple[Path, str | None]:
    """Resolve one package-local filename without allowing manifest path traversal."""
    if not isinstance(name, str) or not name:
        return destination, "filename is missing"
    if "\\" in name or Path(name).is_absolute() or Path(name).name != name:
        return destination, "filename must be a package-local basename"
    path = (destination / name).resolve()
    if path.parent != destination.resolve():
        return destination, "filename escapes package directory"
    return path, None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
