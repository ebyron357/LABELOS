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
    spec_path = destination / "label-spec.json"
    spec_path.write_text(
        json.dumps(spec.to_package_dict(artwork_destination.name), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    report_path = destination / "validation-report.json"
    report_path.write_text(json.dumps(report.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest = {
        "schema_version": 2,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "files": _manifest_files(artwork_destination, spec_path, report_path),
        "validation_report": {
            "file": report_path.name,
            "passed": report.passed,
        },
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
        return ["manifest.json has an unsupported schema version"]
    entries = manifest.get("files")
    if not isinstance(entries, dict) or not entries:
        return ["manifest.json has no file integrity entries"]

    failures: list[str] = []
    expected_files = set(entries) | {"manifest.json"}
    for filename, entry in entries.items():
        if not _is_safe_package_filename(filename):
            failures.append(f"manifest file path is unsafe: {filename!r}")
            continue
        if not isinstance(entry, dict):
            failures.append(f"manifest entry is invalid: {filename}")
            continue
        path = destination / filename
        if not path.is_file() or path.is_symlink():
            failures.append(f"packaged file is missing or not regular: {filename}")
            continue
        if entry.get("bytes") != path.stat().st_size:
            failures.append(f"packaged file size mismatch: {filename}")
        if entry.get("sha256") != _sha256(path):
            failures.append(f"packaged file checksum mismatch: {filename}")

    actual_files = {
        path.relative_to(destination).as_posix()
        for path in destination.rglob("*")
        if path.is_file() or path.is_symlink()
    }
    unexpected = sorted(actual_files - expected_files)
    if unexpected:
        failures.extend(f"unexpected package file: {filename}" for filename in unexpected)

    if "label-spec.json" not in entries:
        failures.append("manifest.json has no label specification entry")
    else:
        try:
            packaged_spec = json.loads((destination / "label-spec.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            failures.append(f"label specification is invalid: {error}")
        else:
            artwork_file = packaged_spec.get("artwork") if isinstance(packaged_spec, dict) else None
            if not _is_safe_package_filename(artwork_file) or artwork_file not in entries:
                failures.append("label specification does not reference a packaged artwork file")

    report_entry = manifest.get("validation_report")
    if not isinstance(report_entry, dict) or report_entry.get("file") != "validation-report.json":
        failures.append("manifest.json has no valid validation report entry")
    elif report_entry.get("passed") is not True:
        failures.append("manifest.json records a failing validation report")
    else:
        try:
            report = json.loads((destination / "validation-report.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            failures.append(f"validation report is invalid: {error}")
        else:
            if report.get("passed") is not True:
                failures.append("validation report does not pass")
    return failures


def _manifest_files(*paths: Path) -> dict[str, dict[str, int | str]]:
    return {
        path.name: {"sha256": _sha256(path), "bytes": path.stat().st_size}
        for path in paths
    }


def _is_safe_package_filename(filename: object) -> bool:
    return (
        isinstance(filename, str)
        and bool(filename)
        and Path(filename).name == filename
        and filename not in {".", ".."}
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
