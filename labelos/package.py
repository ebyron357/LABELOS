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
    manifest = {
        "schema_version": 2,
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
        "spec": report.metadata.get("spec", {}),
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
    except json.JSONDecodeError as error:
        return [f"manifest.json is invalid JSON: {error}"]
    if manifest.get("schema_version") != 2:
        return ["manifest.json has an unsupported schema_version"]

    failures: list[str] = []
    expected_files = {"manifest.json"}
    entries: dict[str, Path] = {}
    for key in ("artwork", "validation_report"):
        entry = manifest.get(key)
        if not isinstance(entry, dict):
            failures.append(f"{key} entry is missing or invalid")
            continue
        filename = entry.get("file")
        if not _is_safe_filename(filename):
            failures.append(f"{key} file path is unsafe")
            continue
        path = destination / filename
        expected_files.add(filename)
        entries[key] = path
        if path.is_symlink() or not path.is_file():
            failures.append(f"{key} file is missing or unsafe: {filename}")
            continue
        if entry.get("bytes") != path.stat().st_size:
            failures.append(f"{key} byte-size mismatch: {filename}")
        if entry.get("sha256") != _sha256(path):
            failures.append(f"{key} checksum mismatch: {filename}")

    if not failures and "validation_report" in entries:
        try:
            report = json.loads(entries["validation_report"].read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            failures.append(f"validation report is invalid JSON: {error}")
        else:
            if not isinstance(report, dict) or report.get("passed") is not True:
                failures.append("validation report does not record a passing validation")
            if manifest["validation_report"].get("passed") is not True:
                failures.append("manifest does not record a passing validation")

    actual_files = {path.name for path in destination.iterdir()}
    unexpected = sorted(actual_files - expected_files)
    if unexpected:
        failures.append(f"unexpected package files: {', '.join(unexpected)}")
    return failures


def _is_safe_filename(value: object) -> bool:
    if not isinstance(value, str) or not value:
        return False
    path = Path(value)
    return not path.is_absolute() and path.parent == Path(".")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
