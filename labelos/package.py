"""Create traceable production release packages from passing validation reports."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

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
    spec_payload = report.metadata.get("spec")
    if not isinstance(spec_payload, dict):
        raise TypeError("Validation report is missing the canonical label specification")
    spec_path.write_text(json.dumps(spec_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest = {
        "schema_version": _PACKAGE_SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "artwork": _file_entry(artwork_destination),
        "validation_report": {**_file_entry(report_path), "passed": report.passed},
        "label_spec": _file_entry(spec_path),
        "spec": spec_payload,
    }
    manifest_path = destination / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest_path


def verify_package(destination: Path) -> list[str]:
    """Return integrity failures for a release package."""
    destination = destination.resolve()
    manifest_path = destination / "manifest.json"
    if not _is_regular_file(manifest_path):
        return ["manifest.json is missing"]
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return [f"manifest.json is invalid JSON: {error}"]
    if not isinstance(manifest, dict):
        return ["manifest.json must contain an object"]
    failures: list[str] = []
    if manifest.get("schema_version") != _PACKAGE_SCHEMA_VERSION:
        failures.append(f"unsupported manifest schema version: {manifest.get('schema_version')!r}")
    entries: dict[str, Path] = {}
    for key in ("artwork", "validation_report", "label_spec"):
        path = _validate_entry(destination, key, manifest.get(key), failures)
        if path is not None:
            entries[key] = path
    _validate_report_and_spec(manifest, entries, failures)
    return failures


def _file_entry(path: Path) -> dict[str, str | int]:
    return {"file": path.name, "sha256": _sha256(path), "bytes": path.stat().st_size}


def _is_regular_file(path: Path) -> bool:
    return path.is_file() and not path.is_symlink()


def _validate_entry(
    destination: Path, key: str, entry: object, failures: list[str]
) -> Path | None:
    if not isinstance(entry, dict):
        failures.append(f"{key} manifest entry is missing or invalid")
        return None
    filename = entry.get("file")
    if not isinstance(filename, str) or not _is_package_filename(filename):
        failures.append(f"{key} file path is invalid")
        return None
    path = destination / filename
    if not _is_regular_file(path):
        failures.append(f"{key} file is missing or is not a regular file: {filename}")
        return None
    digest = entry.get("sha256")
    if not isinstance(digest, str) or _SHA256_RE.fullmatch(digest) is None:
        failures.append(f"{key} SHA-256 is invalid: {filename}")
    elif digest != _sha256(path):
        failures.append(f"{key} checksum mismatch: {filename}")
    if not isinstance(entry.get("bytes"), int) or entry["bytes"] != path.stat().st_size:
        failures.append(f"{key} byte count mismatch: {filename}")
    return path


def _is_package_filename(value: str) -> bool:
    path = Path(value)
    return path.name == value and value not in {"", ".", ".."} and not path.is_absolute()


def _validate_report_and_spec(
    manifest: dict, entries: dict[str, Path], failures: list[str]
) -> None:
    report_path = entries.get("validation_report")
    spec_path = entries.get("label_spec")
    if report_path is None or spec_path is None:
        return
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        failures.append(f"package JSON artifact is invalid: {error}")
        return
    if not isinstance(report, dict) or report.get("passed") is not True:
        failures.append("validation report does not record a passing result")
    report_entry = manifest.get("validation_report")
    if not isinstance(report_entry, dict) or report_entry.get("passed") is not True:
        failures.append("manifest does not record a passing validation result")
    if not isinstance(spec, dict) or manifest.get("spec") != spec:
        failures.append("manifest specification does not match label-spec.json")
    if not isinstance(report, dict) or report.get("metadata", {}).get("spec") != spec:
        failures.append("validation report specification does not match label-spec.json")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
