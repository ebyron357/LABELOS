"""Create traceable production release packages from passing validation reports."""

from __future__ import annotations

import hashlib
import json
import os
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
    spec_path = destination / "label-spec.json"
    spec_path.write_text(
        json.dumps(_package_spec(spec, artwork_destination.name), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    report_path = destination / "validation-report.json"
    report_path.write_text(json.dumps(report.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest = {
        "schema_version": 2,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "artifacts": {
            "artwork": _artifact(artwork_destination),
            "label_spec": _artifact(spec_path),
            "validation_report": _artifact(report_path),
        },
    }
    manifest_path = destination / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest_path


def verify_package(destination: Path) -> list[str]:
    """Return integrity failures for a release package."""
    manifest_path = destination / "manifest.json"
    if not _regular_file(manifest_path):
        return ["manifest.json is missing"]
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        return [f"manifest.json is invalid JSON: {error}"]
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 2:
        return ["manifest schema_version must be 2"]
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict) or set(artifacts) != {
        "artwork",
        "label_spec",
        "validation_report",
    }:
        return ["manifest artifacts must define artwork, label_spec, and validation_report"]

    failures: list[str] = []
    paths: dict[str, Path] = {}
    for key, entry in artifacts.items():
        path, error = _artifact_path(destination, entry)
        if error:
            failures.append(f"{key} {error}")
            continue
        paths[key] = path
        if not _regular_file(path):
            failures.append(f"{key} file is missing or not regular: {path.name}")
            continue
        if entry["sha256"] != _sha256(path):
            failures.append(f"{key} checksum mismatch: {path.name}")
        if entry["bytes"] != path.stat().st_size:
            failures.append(f"{key} byte count mismatch: {path.name}")

    if len({path.name for path in paths.values()}) != len(paths):
        failures.append("manifest artifact file names must be unique")
    expected_files = {"manifest.json", *(path.name for path in paths.values())}
    actual_files = {path.name for path in destination.iterdir()} if destination.is_dir() else set()
    unexpected = actual_files - expected_files
    missing = expected_files - actual_files
    failures.extend(f"unexpected package artifact: {name}" for name in sorted(unexpected))
    failures.extend(f"missing package artifact: {name}" for name in sorted(missing))
    if len(paths) == 3:
        failures.extend(_validate_bindings(paths))
    return failures


def _package_spec(spec: LabelSpec, artwork_file: str) -> dict:
    return {
        "artwork": artwork_file,
        "barcode_value": spec.barcode_value,
        "bleed_mm": spec.bleed_mm,
        "height_mm": spec.height_mm,
        "min_dpi": spec.min_dpi,
        "qr_value": spec.qr_value,
        "required_copy": list(spec.required_copy),
        "safe_area_mm": spec.safe_area_mm,
        "trim_mm": spec.trim_mm,
        "width_mm": spec.width_mm,
    }


def _artifact(path: Path) -> dict:
    return {"file": path.name, "sha256": _sha256(path), "bytes": path.stat().st_size}


def _artifact_path(destination: Path, entry: object) -> tuple[Path, str | None]:
    if not isinstance(entry, dict) or set(entry) != {"file", "sha256", "bytes"}:
        return destination, "metadata is invalid"
    name, digest, size = entry["file"], entry["sha256"], entry["bytes"]
    if not isinstance(name, str) or Path(name).name != name or name in {"", ".", ".."}:
        return destination, "file name is unsafe"
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        return destination / name, "SHA-256 is invalid"
    if not isinstance(size, int) or size < 0:
        return destination / name, "byte count is invalid"
    return destination / name, None


def _regular_file(path: Path) -> bool:
    return path.is_file() and not path.is_symlink() and os.stat(path).st_mode & 0o170000 == 0o100000


def _validate_bindings(paths: dict[str, Path]) -> list[str]:
    failures = []
    try:
        spec = json.loads(paths["label_spec"].read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        failures.append(f"label_spec is invalid JSON: {error}")
    else:
        if not isinstance(spec, dict) or spec.get("artwork") != paths["artwork"].name:
            failures.append("label_spec artwork does not match packaged artwork")
    try:
        report = json.loads(paths["validation_report"].read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        failures.append(f"validation_report is invalid JSON: {error}")
    else:
        if not isinstance(report, dict) or report.get("passed") is not True:
            failures.append("validation_report does not record a passing validation")
    return failures


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
