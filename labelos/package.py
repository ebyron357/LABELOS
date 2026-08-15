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
_REQUIRED_ARTIFACTS = frozenset({"artwork", "label_spec", "validation_report"})


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
        "artifacts": {
            "artwork": _artifact_entry(artwork_destination),
            "label_spec": _artifact_entry(spec_path),
            "validation_report": _artifact_entry(report_path),
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
    failures = _validate_manifest(manifest, destination)
    if failures:
        return failures

    artifacts: dict[str, dict[str, Any]] = manifest["artifacts"]
    artifact_files = {entry["file"] for entry in artifacts.values()}
    expected_files = artifact_files | {"manifest.json"}
    package_files = {path.name for path in destination.iterdir()}
    for name in sorted(package_files - expected_files):
        failures.append(f"unexpected package artifact: {name}")
    for name in sorted(expected_files - package_files):
        failures.append(f"package artifact is missing: {name}")
    for key, entry in artifacts.items():
        path = destination / entry["file"]
        if path.is_symlink() or not path.is_file():
            failures.append(f"{key} artifact is not a regular file: {entry['file']}")
        elif entry["sha256"] != _sha256(path):
            failures.append(f"{key} checksum mismatch: {entry['file']}")
        elif entry["bytes"] != path.stat().st_size:
            failures.append(f"{key} byte count mismatch: {entry['file']}")
    if failures:
        return failures

    try:
        package_spec = json.loads((destination / artifacts["label_spec"]["file"]).read_text(encoding="utf-8"))
        package_report = json.loads(
            (destination / artifacts["validation_report"]["file"]).read_text(encoding="utf-8")
        )
    except json.JSONDecodeError as error:
        return [f"packaged JSON is invalid: {error}"]
    if package_spec.get("artwork") != artifacts["artwork"]["file"]:
        failures.append("label spec artwork does not reference the packaged artwork")
    if package_report.get("passed") is not True:
        failures.append("validation report does not record a passing result")
    return failures


def _package_spec(spec: LabelSpec, artwork_name: str) -> dict[str, Any]:
    return {
        "artwork": artwork_name,
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


def _artifact_entry(path: Path) -> dict[str, Any]:
    return {"file": path.name, "sha256": _sha256(path), "bytes": path.stat().st_size}


def _validate_manifest(manifest: Any, destination: Path) -> list[str]:
    if not isinstance(manifest, dict) or manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        return [f"unsupported manifest schema (expected {MANIFEST_SCHEMA_VERSION})"]
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict) or set(artifacts) != _REQUIRED_ARTIFACTS:
        return ["manifest artifacts must contain artwork, label_spec, and validation_report"]

    failures = []
    filenames: set[str] = set()
    for key, entry in artifacts.items():
        if not isinstance(entry, dict):
            failures.append(f"{key} artifact metadata is invalid")
            continue
        filename, digest, size = entry.get("file"), entry.get("sha256"), entry.get("bytes")
        if not isinstance(filename, str) or not _is_safe_filename(filename):
            failures.append(f"{key} artifact filename is unsafe")
        elif filename in filenames:
            failures.append(f"{key} artifact filename is duplicated: {filename}")
        else:
            filenames.add(filename)
        if not isinstance(digest, str) or not _is_sha256(digest):
            failures.append(f"{key} artifact SHA-256 is invalid")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            failures.append(f"{key} artifact byte count is invalid")
    return failures


def _is_safe_filename(filename: str) -> bool:
    return Path(filename).name == filename and filename not in {"", ".", ".."}


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
