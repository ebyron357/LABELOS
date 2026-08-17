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
    """Return fail-closed integrity failures for a release package."""
    if destination.is_symlink():
        return ["package directory is a symbolic link"]
    manifest_path = destination / "manifest.json"
    if not manifest_path.is_file() or manifest_path.is_symlink():
        return ["manifest.json is missing"]
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return [f"manifest.json is invalid JSON: {error}"]
    if not isinstance(manifest, dict):
        return ["manifest.json must contain an object"]
    failures = []
    if manifest.get("schema_version") != 2:
        failures.append("manifest schema_version must be 2")
    if not isinstance(manifest.get("spec"), dict):
        failures.append("manifest spec must be an object")

    entries = {
        key: _manifest_entry(manifest.get(key), key, failures)
        for key in ("artwork", "validation_report")
    }
    expected_files = {"manifest.json"}
    for key, entry in entries.items():
        if entry is None:
            continue
        expected_files.add(entry["file"])
        path = destination / entry["file"]
        if not path.is_file():
            failures.append(f"{key} file is missing: {entry['file']}")
            continue
        if path.is_symlink():
            failures.append(f"{key} file is a symbolic link: {entry['file']}")
            continue
        if path.stat().st_size != entry["bytes"]:
            failures.append(f"{key} byte count mismatch: {entry['file']}")
        if _sha256(path) != entry["sha256"]:
            failures.append(f"{key} checksum mismatch: {entry['file']}")

    if len(expected_files) != 3:
        failures.append("manifest artifact file names must be distinct")
    if destination.is_dir():
        for path in sorted(destination.iterdir()):
            if path.name not in expected_files:
                failures.append(f"untracked package entry: {path.name}")

    report_entry = entries["validation_report"]
    artwork_entry = entries["artwork"]
    if report_entry is not None and artwork_entry is not None:
        _verify_report_binding(destination / report_entry["file"], manifest, artwork_entry["file"], failures)
    return failures


def _manifest_entry(entry: object, key: str, failures: list[str]) -> dict[str, object] | None:
    if not isinstance(entry, dict):
        failures.append(f"manifest {key} entry must be an object")
        return None
    filename = entry.get("file")
    digest = entry.get("sha256")
    byte_count = entry.get("bytes")
    if not isinstance(filename, str) or not filename or Path(filename).name != filename:
        failures.append(f"manifest {key} file must be a plain filename")
        return None
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        failures.append(f"manifest {key} sha256 must be a lowercase SHA-256 digest")
        return None
    if not isinstance(byte_count, int) or byte_count < 0:
        failures.append(f"manifest {key} bytes must be a non-negative integer")
        return None
    return {"file": filename, "sha256": digest, "bytes": byte_count}


def _verify_report_binding(
    report_path: Path, manifest: dict, artwork_filename: object, failures: list[str]
) -> None:
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        failures.append(f"validation report is invalid JSON: {error}")
        return
    if not isinstance(report, dict):
        failures.append("validation report must contain an object")
        return
    if report.get("passed") is not True or manifest["validation_report"].get("passed") is not True:
        failures.append("validation report did not pass")
    if report.get("metadata", {}).get("spec") != manifest.get("spec"):
        failures.append("validation report spec does not match manifest spec")
    if Path(str(report.get("source", ""))).name != artwork_filename:
        failures.append("validation report source does not match manifest artwork")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
