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
    """Return strict integrity and consistency failures for a release package."""
    manifest_path = destination / "manifest.json"
    if not manifest_path.is_file() or manifest_path.is_symlink():
        return ["manifest.json is missing"]
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        return [f"manifest.json is invalid JSON: {error}"]

    failures: list[str] = []
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 2:
        return ["manifest.json has an unsupported or invalid schema_version"]
    expected_keys = {"schema_version", "created_at", "artwork", "validation_report", "spec"}
    if set(manifest) != expected_keys:
        return ["manifest.json has unexpected or missing fields"]
    if not isinstance(manifest["created_at"], str) or not isinstance(manifest["spec"], dict):
        return ["manifest.json has invalid metadata fields"]

    entries: dict[str, tuple[Path, dict]] = {}
    for key in ("artwork", "validation_report"):
        entry = manifest[key]
        if not isinstance(entry, dict) or set(entry) != {"file", "sha256", "bytes"} | (
            {"passed"} if key == "validation_report" else set()
        ):
            failures.append(f"{key} manifest entry has invalid fields")
            continue
        filename = entry["file"]
        if not _safe_filename(filename):
            failures.append(f"{key} filename is unsafe")
            continue
        if not isinstance(entry["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]):
            failures.append(f"{key} checksum is invalid")
            continue
        if not isinstance(entry["bytes"], int) or entry["bytes"] < 0:
            failures.append(f"{key} byte count is invalid")
            continue
        if key == "validation_report" and not isinstance(entry["passed"], bool):
            failures.append("validation_report passed flag is invalid")
            continue
        entries[key] = (destination / filename, entry)

    if len(entries) == 2 and entries["artwork"][0] == entries["validation_report"][0]:
        failures.append("artwork and validation report must be different files")
    for key, (path, entry) in entries.items():
        if not path.is_file() or path.is_symlink():
            failures.append(f"{key} file is missing: {path.name}")
        else:
            if entry["sha256"] != _sha256(path):
                failures.append(f"{key} checksum mismatch: {path.name}")
            if entry["bytes"] != path.stat().st_size:
                failures.append(f"{key} byte count mismatch: {path.name}")

    expected_files = {"manifest.json"} | {path.name for path, _ in entries.values()}
    actual_files = {path.name for path in destination.iterdir()} if destination.is_dir() else set()
    unexpected = sorted(actual_files - expected_files)
    if unexpected:
        failures.append(f"package contains unexpected files: {', '.join(unexpected)}")

    report_entry = entries.get("validation_report")
    artwork_entry = entries.get("artwork")
    if report_entry and report_entry[0].is_file() and not report_entry[0].is_symlink():
        try:
            report = json.loads(report_entry[0].read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            failures.append("validation report is invalid JSON")
        else:
            if not isinstance(report, dict):
                failures.append("validation report is invalid")
            else:
                if report.get("passed") is not True or report_entry[1]["passed"] is not True:
                    failures.append("validation report did not pass")
                metadata = report.get("metadata")
                if not isinstance(metadata, dict) or metadata.get("spec") != manifest["spec"]:
                    failures.append("validation report spec does not match manifest")
                if artwork_entry and Path(str(report.get("source", ""))).name != artwork_entry[0].name:
                    failures.append("validation report source does not match artwork")
    return failures


def _safe_filename(value: object) -> bool:
    if not isinstance(value, str) or not value or value in {".", ".."}:
        return False
    path = Path(value)
    return not path.is_absolute() and len(path.parts) == 1 and path.name == value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
