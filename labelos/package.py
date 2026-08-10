"""Create traceable production release packages from passing validation reports."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
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
    destination.mkdir(parents=True)
    artwork_destination = destination / spec.artwork.name
    shutil.copy2(spec.artwork, artwork_destination)
    report_path = destination / "validation-report.json"
    report_path.write_text(json.dumps(report.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    spec_path = destination / "label-spec.json"
    spec_path.write_text(
        json.dumps(spec.to_dict(artwork=artwork_destination.name), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    manifest = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "artwork": _manifest_entry(artwork_destination),
        "validation_report": {**_manifest_entry(report_path), "passed": report.passed},
        "label_spec": _manifest_entry(spec_path),
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

    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        return ["manifest schema_version must be 1"]

    failures: list[str] = []
    entries: dict[str, Path] = {}
    for key in ("artwork", "validation_report", "label_spec"):
        path, errors = _verify_entry(destination, key, manifest.get(key))
        failures.extend(errors)
        if path is not None:
            entries[key] = path
    if failures:
        return failures

    try:
        validation_report = json.loads(entries["validation_report"].read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        failures.append(f"validation_report is invalid JSON: {error}")
    else:
        if not isinstance(validation_report, dict) or validation_report.get("passed") is not True:
            failures.append("validation_report does not record a passing validation")
    try:
        label_spec = json.loads(entries["label_spec"].read_text(encoding="utf-8"))
        LabelSpec.from_dict(label_spec, destination)
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        failures.append(f"label_spec is invalid: {error}")
    else:
        if label_spec.get("artwork") != entries["artwork"].name:
            failures.append("label_spec artwork does not match manifest artwork")
    return failures


def _manifest_entry(path: Path) -> dict[str, str | int]:
    return {"file": path.name, "sha256": _sha256(path), "bytes": path.stat().st_size}


def _verify_entry(destination: Path, key: str, entry: Any) -> tuple[Path | None, list[str]]:
    if not isinstance(entry, dict):
        return None, [f"{key} manifest entry is invalid"]
    filename, digest, byte_count = entry.get("file"), entry.get("sha256"), entry.get("bytes")
    if not _is_safe_filename(filename):
        return None, [f"{key} manifest filename is unsafe"]
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        return None, [f"{key} manifest SHA-256 is invalid"]
    if not isinstance(byte_count, int) or isinstance(byte_count, bool) or byte_count < 0:
        return None, [f"{key} manifest byte count is invalid"]
    path = destination / filename
    if path.is_symlink() or not path.is_file():
        return None, [f"{key} file is missing: {filename}"]
    if path.stat().st_size != byte_count:
        return None, [f"{key} byte count mismatch: {filename}"]
    if _sha256(path) != digest:
        return None, [f"{key} checksum mismatch: {filename}"]
    return path, []


def _is_safe_filename(value: Any) -> bool:
    return isinstance(value, str) and bool(value) and Path(value).name == value and value not in {".", ".."}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
