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
                "barcode_value": spec.barcode_value,
                "bleed_mm": spec.bleed_mm,
                "height_mm": spec.height_mm,
                "min_dpi": spec.min_dpi,
                "qr_value": spec.qr_value,
                "required_copy": list(spec.required_copy),
                "safe_area_mm": spec.safe_area_mm,
                "trim_mm": spec.trim_mm,
                "width_mm": spec.width_mm,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    manifest = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "artwork": {
            "file": artwork_destination.name,
            "sha256": _sha256(artwork_destination),
            "bytes": artwork_destination.stat().st_size,
        },
        "validation_report": {
            "file": report_path.name,
            "sha256": _sha256(report_path),
            "bytes": report_path.stat().st_size,
            "passed": report.passed,
        },
        "label_spec": {
            "file": spec_path.name,
            "sha256": _sha256(spec_path),
            "bytes": spec_path.stat().st_size,
        },
        "spec": report.metadata.get("spec", {}),
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
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        return ["manifest.json has an unsupported schema version"]
    failures = []
    for key in ("artwork", "validation_report", "label_spec"):
        entry = manifest.get(key)
        if not isinstance(entry, dict):
            failures.append(f"{key} entry is missing or invalid")
            continue
        name = entry.get("file")
        if not _is_package_filename(name):
            failures.append(f"{key} file path is invalid")
            continue
        path = destination / name
        if not path.is_file():
            failures.append(f"{key} file is missing: {name}")
            continue
        if entry.get("sha256") != _sha256(path):
            failures.append(f"{key} checksum mismatch: {name}")
            continue
        if entry.get("bytes") != path.stat().st_size:
            failures.append(f"{key} byte count mismatch: {name}")
    return failures


def _is_package_filename(value: object) -> bool:
    """Accept only a single safe filename, so a manifest cannot escape its package."""
    return (
        isinstance(value, str)
        and bool(value)
        and value not in {".", ".."}
        and "/" not in value
        and "\\" not in value
        and Path(value).name == value
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
