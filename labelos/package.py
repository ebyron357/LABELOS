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
    manifest_path = destination / "manifest.json"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        return ["manifest.json is missing"]
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        return [f"manifest.json is invalid JSON: {error}"]
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 2:
        return ["manifest.json has an unsupported schema version"]
    failures: list[str] = []
    expected_paths = {"manifest.json"}
    for key in ("artwork", "validation_report"):
        entry = manifest.get(key, {})
        if not isinstance(entry, dict):
            failures.append(f"{key} manifest entry is invalid")
            continue
        name = entry.get("file")
        if not _safe_package_name(name):
            failures.append(f"{key} file name is unsafe")
            continue
        expected_paths.add(name)
        path = destination / name
        if path.is_symlink() or not path.is_file():
            failures.append(f"{key} file is missing: {name}")
            continue
        if entry.get("bytes") != path.stat().st_size:
            failures.append(f"{key} byte-size mismatch: {name}")
        if entry.get("sha256") != _sha256(path):
            failures.append(f"{key} checksum mismatch: {name}")
        if key == "validation_report":
            _verify_validation_report(path, entry, failures)
    for path in destination.iterdir():
        if path.name not in expected_paths:
            failures.append(f"unexpected package file: {path.name}")
        elif path.is_symlink():
            failures.append(f"package file is a symlink: {path.name}")
    return failures


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_package_name(value: object) -> bool:
    return (
        isinstance(value, str)
        and value == Path(value).name
        and value not in {"", ".", ".."}
        and not Path(value).is_absolute()
    )


def _verify_validation_report(path: Path, entry: dict, failures: list[str]) -> None:
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        failures.append(f"validation report is invalid JSON: {error}")
        return
    if not isinstance(report, dict) or report.get("passed") is not True:
        failures.append("validation report does not record a passing validation")
    if entry.get("passed") is not True:
        failures.append("manifest does not record a passing validation")
