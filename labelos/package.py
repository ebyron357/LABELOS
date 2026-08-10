"""Create traceable production release packages from passing validation reports."""

from __future__ import annotations

import hashlib
import json
import re
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
    package_spec = spec.to_dict(artwork_destination.name)
    spec_path = destination / "label-spec.json"
    spec_path.write_text(json.dumps(package_spec, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report_path = destination / "validation-report.json"
    report_path.write_text(json.dumps(report.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
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
        "spec": {
            "file": spec_path.name,
            "sha256": _sha256(spec_path),
            "bytes": spec_path.stat().st_size,
        },
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
    failures: list[str] = []
    if manifest.get("schema_version") != 1:
        failures.append("manifest schema_version must be 1")
    entries: dict[str, Path] = {}
    for key in ("artwork", "validation_report", "spec"):
        entry = manifest.get(key)
        if not isinstance(entry, dict):
            failures.append(f"{key} entry is missing or invalid")
            continue
        path = _package_file(destination, entry.get("file"))
        if path is None:
            failures.append(f"{key} file must be a package-local filename")
            continue
        entries[key] = path
        if not path.is_file() or path.is_symlink():
            failures.append(f"{key} file is missing or is not a regular file: {path.name}")
            continue
        if entry.get("bytes") != path.stat().st_size:
            failures.append(f"{key} byte count mismatch: {path.name}")
        expected_hash = entry.get("sha256")
        if not isinstance(expected_hash, str) or not _SHA256.fullmatch(expected_hash):
            failures.append(f"{key} checksum is not a lowercase SHA-256 digest")
        elif expected_hash != _sha256(path):
            failures.append(f"{key} checksum mismatch: {path.name}")
    _validate_report_and_spec(entries, failures)
    return failures


def _package_file(destination: Path, value: object) -> Path | None:
    if not isinstance(value, str) or not value or Path(value).name != value:
        return None
    return destination / value


def _validate_report_and_spec(entries: dict[str, Path], failures: list[str]) -> None:
    report_path = entries.get("validation_report")
    spec_path = entries.get("spec")
    if report_path is None or spec_path is None:
        return
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        failures.append(f"validation report is invalid JSON: {error}")
        return
    try:
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        failures.append(f"label spec is invalid JSON: {error}")
        return
    if not isinstance(report, dict) or report.get("passed") is not True:
        failures.append("validation report does not record a passing validation")
    elif report.get("metadata", {}).get("spec") != spec:
        failures.append("validation report spec does not match packaged label spec")


_SHA256 = re.compile(r"[0-9a-f]{64}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
