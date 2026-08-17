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
    manifest_path = destination / "manifest.json"
    if not manifest_path.is_file():
        return ["manifest.json is missing"]
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        return [f"manifest.json is invalid JSON: {error}"]
    if not isinstance(manifest, dict):
        return ["manifest.json must contain a JSON object"]
    if manifest.get("schema_version") != 1:
        return ["manifest.json has an unsupported schema_version"]
    failures: list[str] = []
    declared_files = {"manifest.json"}
    for key in ("artwork", "validation_report"):
        entry = manifest.get(key)
        if not isinstance(entry, dict):
            failures.append(f"{key} manifest entry is invalid")
            continue
        filename = entry.get("file")
        if not _is_package_filename(filename):
            failures.append(f"{key} file name is invalid")
            continue
        if filename in declared_files:
            failures.append(f"{key} file duplicates another manifest entry: {filename}")
            continue
        declared_files.add(filename)
        path = destination / filename
        if path.is_symlink() or not path.is_file():
            failures.append(f"{key} file is missing or not a regular file: {filename}")
            continue
        expected_hash = entry.get("sha256")
        checksum_matches = False
        if not isinstance(expected_hash, str) or not _is_sha256(expected_hash):
            failures.append(f"{key} SHA-256 is invalid: {filename}")
        else:
            checksum_matches = expected_hash == _sha256(path)
            if not checksum_matches:
                failures.append(f"{key} checksum mismatch: {filename}")
        expected_bytes = entry.get("bytes")
        if key == "artwork" and checksum_matches and (
            not isinstance(expected_bytes, int)
            or isinstance(expected_bytes, bool)
            or expected_bytes != path.stat().st_size
        ):
            failures.append(f"{key} byte count mismatch: {filename}")
    if not failures and destination.is_dir():
        actual_files = {path.name for path in destination.iterdir()}
        unexpected = sorted(actual_files - declared_files)
        if unexpected:
            failures.append(f"package contains untracked files: {', '.join(unexpected)}")
    return failures


def _is_package_filename(value: object) -> bool:
    """Release packages are flat, so manifest paths cannot escape their directory."""
    return isinstance(value, str) and Path(value).name == value and value not in {"", ".", ".."}


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value.lower())


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
