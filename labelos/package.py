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
    spec_path.write_text(json.dumps(_spec_payload(spec), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "artwork": _manifest_entry(artwork_destination),
        "validation_report": _manifest_entry(report_path),
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
        return ["manifest root must be a JSON object"]
    if type(manifest.get("schema_version")) is not int or manifest["schema_version"] != 1:
        return ["manifest schema_version must be 1"]
    failures = []
    for key in ("artwork", "validation_report", "label_spec"):
        entry = manifest.get(key)
        if not isinstance(entry, dict):
            failures.append(f"{key} manifest entry is missing or invalid")
            continue
        filename = entry.get("file")
        if not _safe_filename(filename):
            failures.append(f"{key} file name is unsafe: {filename!r}")
            continue
        path = destination / filename
        if path.resolve().parent != destination.resolve():
            failures.append(f"{key} file resolves outside package: {filename}")
        elif not path.is_file():
            failures.append(f"{key} file is missing: {filename}")
        elif entry.get("bytes") != path.stat().st_size:
            failures.append(f"{key} byte count mismatch: {filename}")
        elif entry.get("sha256") != _sha256(path):
            failures.append(f"{key} checksum mismatch: {filename}")
    return failures


def _manifest_entry(path: Path) -> dict[str, str | int]:
    return {"file": path.name, "sha256": _sha256(path), "bytes": path.stat().st_size}


def _spec_payload(spec: LabelSpec) -> dict[str, object]:
    payload: dict[str, object] = {
        "artwork": spec.artwork.name,
        "width_mm": spec.width_mm,
        "height_mm": spec.height_mm,
        "trim_mm": spec.trim_mm,
        "bleed_mm": spec.bleed_mm,
        "safe_area_mm": spec.safe_area_mm,
        "min_dpi": spec.min_dpi,
        "required_copy": list(spec.required_copy),
    }
    if spec.barcode_value is not None:
        payload["barcode_value"] = spec.barcode_value
    if spec.qr_value is not None:
        payload["qr_value"] = spec.qr_value
    return payload


def _safe_filename(value: object) -> bool:
    return isinstance(value, str) and value not in {"", ".", ".."} and Path(value).name == value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
