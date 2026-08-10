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
    report_path = destination / "validation-report.json"
    report_path.write_text(json.dumps(report.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    label_spec_path = destination / "label-spec.json"
    label_spec = {"schema_version": 1, "artwork": artwork_destination.name, **report.metadata["spec"]}
    label_spec_path.write_text(json.dumps(label_spec, indent=2, sort_keys=True) + "\n", encoding="utf-8")
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
            "file": label_spec_path.name,
            "sha256": _sha256(label_spec_path),
            "bytes": label_spec_path.stat().st_size,
        },
    }
    manifest_path = destination / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest_path


def verify_package(destination: Path) -> list[str]:
    """Return integrity failures for a release package."""
    manifest_path = destination / "manifest.json"
    if not manifest_path.is_file() or manifest_path.is_symlink():
        return ["manifest.json is missing"]
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        return [f"manifest.json is invalid JSON: {error}"]
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        return ["manifest schema_version must be 1"]

    failures: list[str] = []
    package_files: dict[str, Path] = {}
    for key in ("artwork", "validation_report", "label_spec"):
        entry = manifest.get(key)
        if not isinstance(entry, dict):
            failures.append(f"{key} manifest entry is missing or invalid")
            continue
        filename = entry.get("file")
        if not _package_filename(filename):
            failures.append(f"{key} file must be a package-local filename")
            continue
        path = destination / filename
        package_files[key] = path
        if not path.is_file() or path.is_symlink():
            failures.append(f"{key} file is missing or not a regular file: {filename}")
            continue
        if not isinstance(entry.get("bytes"), int) or entry["bytes"] < 0:
            failures.append(f"{key} byte count is invalid: {filename}")
        elif path.stat().st_size != entry["bytes"]:
            failures.append(f"{key} byte count mismatch: {filename}")
        checksum = entry.get("sha256")
        if not isinstance(checksum, str) or not re.fullmatch(r"[0-9a-f]{64}", checksum):
            failures.append(f"{key} checksum is invalid: {filename}")
        elif checksum != _sha256(path):
            failures.append(f"{key} checksum mismatch: {filename}")

    if failures:
        return failures
    try:
        report = json.loads(package_files["validation_report"].read_text(encoding="utf-8"))
        label_spec = json.loads(package_files["label_spec"].read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        return [f"package JSON is invalid: {error}"]
    if not isinstance(report, dict) or report.get("passed") is not True:
        failures.append("validation report does not record a passing validation")
    if not isinstance(label_spec, dict) or label_spec.get("schema_version") != 1:
        failures.append("label spec schema_version must be 1")
    elif label_spec.get("artwork") != manifest["artwork"]["file"]:
        failures.append("label spec artwork does not match manifest artwork")
    elif not isinstance(report.get("metadata"), dict) or report["metadata"].get("spec") != {
        key: value for key, value in label_spec.items() if key not in {"schema_version", "artwork"}
    }:
        failures.append("validation report spec does not match label spec")
    return failures


def _package_filename(value: object) -> bool:
    return isinstance(value, str) and bool(value) and Path(value).name == value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
