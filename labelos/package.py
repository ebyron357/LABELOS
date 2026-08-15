"""Create traceable production release packages from passing validation reports."""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from .models import LabelSpec, Report

MANIFEST_SCHEMA_VERSION = 2
MANIFEST_NAME = "manifest.json"
REPORT_NAME = "validation-report.json"
SPEC_NAME = "label-spec.json"


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
    spec_path = destination / SPEC_NAME
    spec_path.write_text(
        json.dumps(_serialized_spec(spec), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    report_path = destination / REPORT_NAME
    report_path.write_text(json.dumps(report.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "artifacts": {
            "artwork": _artifact(artwork_destination),
            "label_spec": _artifact(spec_path),
            "validation_report": _artifact(report_path),
        },
    }
    manifest_path = destination / MANIFEST_NAME
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest_path


def verify_package(destination: Path) -> list[str]:
    """Return integrity failures for a release package."""
    destination = destination.resolve()
    manifest_path = destination / MANIFEST_NAME
    if not manifest_path.is_file() or manifest_path.is_symlink():
        return [f"{MANIFEST_NAME} is missing or not a regular file"]
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        return [f"{MANIFEST_NAME} is invalid JSON: {error}"]
    if not isinstance(manifest, dict) or manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        return [f"Unsupported manifest schema; expected version {MANIFEST_SCHEMA_VERSION}"]
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict) or set(artifacts) != {
        "artwork",
        "label_spec",
        "validation_report",
    }:
        return ["Manifest must declare exactly artwork, label_spec, and validation_report artifacts"]

    failures: list[str] = []
    artifact_paths: dict[str, Path] = {}
    seen_names: set[str] = set()
    for key, entry in artifacts.items():
        if not isinstance(entry, dict):
            failures.append(f"{key} manifest entry is invalid")
            continue
        name = entry.get("file")
        if not _safe_artifact_name(name) or name in seen_names:
            failures.append(f"{key} has an unsafe or duplicate artifact filename")
            continue
        seen_names.add(name)
        path = destination / name
        artifact_paths[key] = path
        if not path.is_file() or path.is_symlink():
            failures.append(f"{key} file is missing or not a regular file: {name}")
            continue
        if entry.get("bytes") != path.stat().st_size:
            failures.append(f"{key} byte count mismatch: {name}")
        expected_hash = entry.get("sha256")
        if not isinstance(expected_hash, str) or len(expected_hash) != 64 or any(
            char not in "0123456789abcdef" for char in expected_hash.lower()
        ):
            failures.append(f"{key} checksum is invalid: {name}")
        elif expected_hash != _sha256(path):
            failures.append(f"{key} checksum mismatch: {name}")

    allowed_files = {MANIFEST_NAME, *seen_names}
    if destination.is_dir():
        for child in destination.iterdir():
            if child.name not in allowed_files:
                failures.append(f"Unexpected package artifact: {child.name}")
            elif not child.is_file() or child.is_symlink():
                failures.append(f"Package artifact is not a regular file: {child.name}")
    else:
        failures.append("Package destination is not a directory")

    if failures:
        return failures
    try:
        packaged_spec = json.loads(artifact_paths["label_spec"].read_text(encoding="utf-8"))
        packaged_report = json.loads(artifact_paths["validation_report"].read_text(encoding="utf-8"))
    except (KeyError, OSError, json.JSONDecodeError) as error:
        return [f"Package metadata is invalid JSON: {error}"]
    if not isinstance(packaged_spec, dict) or packaged_spec.get("artwork") != artifacts["artwork"]["file"]:
        failures.append("Packaged label specification does not bind to the packaged artwork")
    if not isinstance(packaged_report, dict) or packaged_report.get("passed") is not True:
        failures.append("Packaged validation report does not record a passing result")
    return failures


def _serialized_spec(spec: LabelSpec) -> dict[str, object]:
    return {
        "artwork": spec.artwork.name,
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


def _artifact(path: Path) -> dict[str, str | int]:
    return {"file": path.name, "sha256": _sha256(path), "bytes": path.stat().st_size}


def _safe_artifact_name(value: object) -> bool:
    return (
        isinstance(value, str)
        and value not in {".", "..", MANIFEST_NAME}
        and Path(value).name == value
        and not Path(value).is_absolute()
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
