"""Create traceable production release packages from passing validation reports."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import LabelSpec, Report


def create_package(spec: LabelSpec, report: Report, destination: Path) -> Path:
    """Create an immutable-style package directory and return its manifest path."""
    if not report.passed:
        raise ValueError("Refusing to package artwork with validation errors")
    destination = destination.resolve()
    if destination.exists():
        raise FileExistsError(f"Package destination already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{destination.name}.", dir=destination.parent))
    try:
        artwork_destination = staging / spec.artwork.name
        shutil.copy2(spec.artwork, artwork_destination)
        report_path = staging / "validation-report.json"
        report_path.write_text(
            json.dumps(report.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        manifest = {
            "schema_version": 2,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "artwork": _manifest_entry(artwork_destination),
            "validation_report": {**_manifest_entry(report_path), "passed": report.passed},
            "spec": report.metadata.get("spec", {}),
        }
        manifest_path = staging / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        os.replace(staging, destination)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return destination / "manifest.json"


def verify_package(destination: Path) -> list[str]:
    """Return integrity failures for a release package."""
    manifest_path = destination / "manifest.json"
    if not manifest_path.is_file():
        return ["manifest.json is missing"]
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        return [f"manifest.json is invalid JSON: {error}"]
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 2:
        return ["manifest.json has an unsupported or missing schema_version"]
    failures: list[str] = []
    expected_files = {"manifest.json"}
    for key in ("artwork", "validation_report"):
        entry = manifest.get(key, {})
        filename = _entry_filename(entry)
        if filename is None:
            failures.append(f"{key} entry is invalid")
            continue
        expected_files.add(filename)
        path = destination / filename
        if not path.is_file():
            failures.append(f"{key} file is missing: {filename}")
            continue
        if path.is_symlink():
            failures.append(f"{key} file must not be a symbolic link: {filename}")
            continue
        if entry.get("bytes") != path.stat().st_size:
            failures.append(f"{key} byte count mismatch: {filename}")
        expected_checksum = entry.get("sha256")
        if not isinstance(expected_checksum, str) or not _is_sha256(expected_checksum):
            failures.append(f"{key} checksum is invalid: {filename}")
        elif expected_checksum != _sha256(path):
            failures.append(f"{key} checksum mismatch: {filename}")
    actual_files = {
        path.relative_to(destination).as_posix()
        for path in destination.rglob("*")
        if path.is_file()
    }
    for filename in sorted(actual_files - expected_files):
        failures.append(f"untracked package file: {filename}")
    for filename in sorted(expected_files - actual_files):
        if filename != "manifest.json":
            continue
        failures.append("manifest.json is missing")
    return failures


def _manifest_entry(path: Path) -> dict[str, str | int]:
    return {"file": path.name, "sha256": _sha256(path), "bytes": path.stat().st_size}


def _entry_filename(entry: Any) -> str | None:
    if not isinstance(entry, dict):
        return None
    filename = entry.get("file")
    if not isinstance(filename, str) or not filename or Path(filename).name != filename:
        return None
    return filename


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value.lower())


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
