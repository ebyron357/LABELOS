"""Create traceable production release packages from passing validation reports."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import LabelSpec, Report

_PACKAGE_SCHEMA_VERSION = 1
_SHA256_RE = re.compile(r"[0-9a-f]{64}")


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
    spec_payload = spec.to_dict(artwork=artwork_destination.name)
    spec_path.write_text(json.dumps(spec_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest = {
        "schema_version": _PACKAGE_SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "artwork": _manifest_entry(artwork_destination),
        "validation_report": {**_manifest_entry(report_path), "passed": report.passed},
        "label_spec": _manifest_entry(spec_path),
        "spec": spec_payload,
    }
    manifest_path = destination / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest_path


def verify_package(destination: Path) -> list[str]:
    """Return integrity failures for a release package."""
    if destination.is_symlink():
        return ["package destination must not be a symbolic link"]
    if not destination.is_dir():
        return ["package destination is missing or is not a directory"]
    manifest_path = destination / "manifest.json"
    if manifest_path.is_symlink():
        return ["manifest.json must not be a symbolic link"]
    if not manifest_path.is_file():
        return ["manifest.json is missing"]
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        return [f"manifest.json is invalid JSON: {error}"]
    if not isinstance(manifest, dict):
        return ["manifest.json root must be an object"]
    if manifest.get("schema_version") != _PACKAGE_SCHEMA_VERSION:
        return ["manifest.json has unsupported schema_version"]

    failures: list[str] = []
    entries: dict[str, Path] = {}
    seen_files: set[str] = set()
    for key in ("artwork", "validation_report", "label_spec"):
        path = _validate_entry(destination, key, manifest.get(key), failures, seen_files)
        if path is not None:
            entries[key] = path
    _validate_report_and_spec(manifest, entries, failures)
    return failures


def _manifest_entry(path: Path) -> dict[str, str | int]:
    return {"file": path.name, "sha256": _sha256(path), "bytes": path.stat().st_size}


def _validate_entry(
    destination: Path, key: str, entry: Any, failures: list[str], seen_files: set[str]
) -> Path | None:
    if not isinstance(entry, dict):
        failures.append(f"{key} manifest entry is missing or invalid")
        return None
    filename = entry.get("file")
    if not isinstance(filename, str) or not _is_package_filename(filename):
        failures.append(f"{key} file path is invalid")
        return None
    if filename in seen_files:
        failures.append(f"{key} file duplicates another manifest entry: {filename}")
        return None
    seen_files.add(filename)
    path = destination / filename
    if path.is_symlink() or not path.is_file():
        failures.append(f"{key} file is missing or is not a regular file: {filename}")
        return None
    digest = entry.get("sha256")
    if not isinstance(digest, str) or _SHA256_RE.fullmatch(digest) is None:
        failures.append(f"{key} SHA-256 is invalid: {filename}")
    elif digest != _sha256(path):
        failures.append(f"{key} checksum mismatch: {filename}")
    byte_count = entry.get("bytes")
    if not isinstance(byte_count, int) or isinstance(byte_count, bool) or byte_count != path.stat().st_size:
        failures.append(f"{key} byte count mismatch: {filename}")
    return path


def _is_package_filename(value: str) -> bool:
    path = Path(value)
    return path.name == value and value not in {"", ".", ".."} and not path.is_absolute()


def _validate_report_and_spec(
    manifest: dict[str, Any], entries: dict[str, Path], failures: list[str]
) -> None:
    report_path = entries.get("validation_report")
    spec_path = entries.get("label_spec")
    artwork_path = entries.get("artwork")
    if report_path is None or spec_path is None or artwork_path is None:
        return
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        failures.append(f"package JSON artifact is invalid: {error}")
        return
    if not isinstance(report, dict) or report.get("passed") is not True:
        failures.append("validation report does not record a passing result")
    if not isinstance(manifest.get("validation_report"), dict) or manifest["validation_report"].get("passed") is not True:
        failures.append("manifest does not record a passing validation result")
    if not isinstance(spec, dict):
        failures.append("label-spec.json must contain an object")
        return
    try:
        LabelSpec.from_dict(spec, spec_path.parent)
    except (TypeError, ValueError) as error:
        failures.append(f"label-spec.json is invalid: {error}")
        return
    if spec.get("artwork") != artwork_path.name:
        failures.append("label-spec.json artwork does not match packaged artwork")
    if manifest.get("spec") != spec:
        failures.append("manifest specification does not match label-spec.json")
    report_spec = report.get("metadata", {}).get("spec") if isinstance(report.get("metadata"), dict) else None
    if report_spec != spec:
        failures.append("validation report specification does not match label-spec.json")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
