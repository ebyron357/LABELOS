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
    if not manifest_path.is_file() or manifest_path.is_symlink():
        return ["manifest.json is missing"]
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        return [f"manifest.json is invalid JSON: {error}"]
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        return ["manifest.json has an unsupported schema"]

    failures: list[str] = []
    expected_files = {"manifest.json"}
    entries: dict[str, dict] = {}
    for key in ("artwork", "validation_report"):
        entry = manifest.get(key)
        if not isinstance(entry, dict):
            failures.append(f"{key} manifest entry is invalid")
            continue
        filename = entry.get("file")
        checksum = entry.get("sha256")
        if not _is_package_filename(filename):
            failures.append(f"{key} filename is unsafe")
            continue
        if filename in expected_files:
            failures.append(f"{key} filename is duplicated: {filename}")
            continue
        expected_files.add(filename)
        entries[key] = entry
        if not _is_sha256(checksum):
            failures.append(f"{key} checksum is invalid: {filename}")
            continue
        path = destination / filename
        if not path.is_file() or path.is_symlink():
            failures.append(f"{key} file is missing: {filename}")
        elif checksum != _sha256(path):
            failures.append(f"{key} checksum mismatch: {filename}")

    artwork = entries.get("artwork")
    if artwork and isinstance(artwork.get("bytes"), int):
        artwork_path = destination / artwork["file"]
        if (
            artwork_path.is_file()
            and not artwork_path.is_symlink()
            and artwork.get("sha256") == _sha256(artwork_path)
            and artwork_path.stat().st_size != artwork["bytes"]
        ):
            failures.append(f"artwork byte count mismatch: {artwork['file']}")
    elif artwork:
        failures.append("artwork byte count is invalid")

    actual_files = {path.name for path in destination.iterdir() if path.is_file() and not path.is_symlink()}
    unsafe_files = [path.name for path in destination.iterdir() if path.is_symlink() or not path.is_file()]
    if unexpected := sorted(actual_files - expected_files):
        failures.append(f"package contains untracked files: {', '.join(unexpected)}")
    if unsafe_files:
        failures.append(f"package contains unsafe entries: {', '.join(sorted(unsafe_files))}")
    return failures


def _is_package_filename(value: object) -> bool:
    return isinstance(value, str) and bool(value) and Path(value).name == value and value not in {".", ".."}


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"[0-9a-f]{64}", value))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
