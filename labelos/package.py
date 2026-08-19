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

_PACKAGE_SCHEMA_VERSION = 2
_SUPPORTED_SCHEMA_VERSIONS = {1, _PACKAGE_SCHEMA_VERSION}
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_RESERVED_FILENAMES = {"manifest.json", "validation-report.json", "label-spec.json"}


def create_package(
    spec: LabelSpec,
    report: Report,
    destination: Path,
    extras: dict[str, dict[str, Any] | str | bytes] | None = None,
) -> Path:
    """Create an immutable-style package directory and return its manifest path."""
    if not report.passed:
        raise ValueError("Refusing to package artwork with validation errors")
    destination = destination.resolve()
    if destination.exists():
        raise FileExistsError(f"Package destination already exists: {destination}")
    destination.mkdir(parents=True)
    artwork_destination = destination / spec.artwork.name
    shutil.copy2(spec.artwork, artwork_destination)
    dependencies = _copy_svg_linked_assets(spec, report, destination)
    report_path = destination / "validation-report.json"
    report_path.write_text(json.dumps(report.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    spec_payload = spec.to_dict(artwork=artwork_destination.name)
    spec_path = destination / "label-spec.json"
    spec_path.write_text(json.dumps(spec_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    extra_manifest: dict[str, Any] = {}
    for filename, payload in (extras or {}).items():
        _assert_package_filename(filename, extra=True)
        target = destination / Path(filename).name
        if isinstance(payload, bytes):
            target.write_bytes(payload)
        elif isinstance(payload, str):
            target.write_text(payload, encoding="utf-8")
        else:
            target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        extra_manifest[target.name] = _manifest_entry(target)
    manifest = {
        "schema_version": _PACKAGE_SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "artwork": _manifest_entry(artwork_destination),
        "artwork_dependencies": dependencies,
        "validation_report": {**_manifest_entry(report_path), "passed": report.passed},
        "label_spec": _manifest_entry(spec_path),
        "extras": extra_manifest,
        "spec": spec_payload,
    }
    manifest_path = destination / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest_path


def verify_package(destination: Path) -> list[str]:
    """Return integrity failures for a release package."""
    destination = destination.resolve()
    manifest_path = destination / "manifest.json"
    if not _is_regular_file(manifest_path):
        return ["manifest.json is missing"]
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return [f"manifest.json is invalid JSON: {error}"]
    if not isinstance(manifest, dict):
        return ["manifest.json must contain a JSON object"]

    failures: list[str] = []
    schema_version = manifest.get("schema_version")
    if schema_version not in _SUPPORTED_SCHEMA_VERSIONS:
        failures.append(f"unsupported manifest schema version: {manifest.get('schema_version')!r}")
    allows_nested_dependencies = schema_version == _PACKAGE_SCHEMA_VERSION

    entries: dict[str, Path] = {}
    for key in ("artwork", "validation_report", "label_spec"):
        path = _validate_entry(destination, key, manifest.get(key), failures)
        if path is not None:
            entries[key] = path

    dependencies = manifest.get("artwork_dependencies", {})
    if schema_version == 1 and dependencies:
        failures.append("schema version 1 does not support artwork dependencies")
    elif not isinstance(dependencies, dict):
        failures.append("artwork dependencies manifest entry must be an object")
    else:
        for name, entry in dependencies.items():
            _validate_entry(
                destination,
                f"artwork dependency:{name}",
                entry,
                failures,
                allow_nested=allows_nested_dependencies,
            )

    extras = manifest.get("extras") or {}
    if extras and not isinstance(extras, dict):
        failures.append("extras manifest entry must be an object")
    else:
        for name, entry in extras.items():
            extra_path = _validate_entry(destination, f"extra:{name}", entry, failures)
            if extra_path is not None and not _is_package_filename(str(entry.get("file", name))):
                failures.append(f"extra file path is invalid: {name}")

    _validate_report_and_spec(manifest, entries, failures)
    return failures


def _assert_package_filename(filename: str, extra: bool = False) -> None:
    if not _is_package_filename(filename):
        raise ValueError(f"Unsafe package extra filename: {filename}")
    if extra and filename in _RESERVED_FILENAMES:
        raise ValueError(f"Unsafe package extra filename: {filename}")


def _manifest_entry(path: Path, file: str | None = None) -> dict[str, str | int]:
    return {"file": file or path.name, "sha256": sha256_file(path), "bytes": path.stat().st_size}


def _is_regular_file(path: Path) -> bool:
    return path.is_file() and not path.is_symlink()


def _is_package_filename(value: str, allow_nested: bool = False) -> bool:
    path = Path(value)
    if value in {"", ".", ".."} or path.is_absolute() or ".." in path.parts:
        return False
    return allow_nested or path.name == value


def _validate_entry(
    destination: Path,
    key: str,
    entry: Any,
    failures: list[str],
    *,
    allow_nested: bool = False,
) -> Path | None:
    if not isinstance(entry, dict):
        failures.append(f"{key} manifest entry is missing or invalid")
        return None

    filename = entry.get("file")
    if not isinstance(filename, str) or not _is_package_filename(filename, allow_nested):
        failures.append(f"{key} file must be a package-relative filename")
        return None

    path = destination / filename
    if not _is_regular_file(path):
        failures.append(f"{key} file is missing or is not a regular file: {filename}")
        return None

    digest = entry.get("sha256")
    if not isinstance(digest, str) or _SHA256_RE.fullmatch(digest) is None:
        failures.append(f"{key} sha256 must be a lowercase SHA-256 digest")
    elif digest != sha256_file(path):
        failures.append(f"{key} checksum mismatch: {filename}")

    byte_count = entry.get("bytes")
    if byte_count is not None and (
        not isinstance(byte_count, int) or isinstance(byte_count, bool) or byte_count != path.stat().st_size
    ):
        failures.append(f"{key} byte count mismatch: {filename}")

    return path


def _copy_svg_linked_assets(
    spec: LabelSpec, report: Report, destination: Path
) -> dict[str, dict[str, str | int]]:
    """Copy validator-approved SVG raster dependencies into the release package."""

    assets = report.metadata.get("svg_linked_assets", [])
    if not isinstance(assets, list) or not all(isinstance(asset, str) for asset in assets):
        raise ValueError("SVG linked asset metadata is invalid")
    manifest: dict[str, dict[str, str | int]] = {}
    source_root = spec.artwork.parent.resolve()
    for relative_name in assets:
        if not _is_package_filename(relative_name, allow_nested=True):
            raise ValueError(f"Unsafe SVG linked asset path: {relative_name}")
        source = source_root / relative_name
        if not _is_regular_file(source):
            raise ValueError(f"SVG linked asset is missing or unsafe: {relative_name}")
        try:
            source.resolve().relative_to(source_root)
        except ValueError as error:
            raise ValueError(f"SVG linked asset escapes artwork directory: {relative_name}") from error
        target = destination / relative_name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        manifest[relative_name] = _manifest_entry(target, file=relative_name)
    return manifest


def _validate_report_and_spec(
    manifest: dict[str, Any], entries: dict[str, Path], failures: list[str]
) -> None:
    report_path = entries.get("validation_report")
    spec_path = entries.get("label_spec")
    artwork_path = entries.get("artwork")
    if report_path is None or spec_path is None or artwork_path is None:
        return

    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        failures.append(f"package JSON artifact is invalid: {error}")
        return

    if not isinstance(report, dict) or report.get("passed") is not True:
        failures.append("validation report does not record a passing result")

    manifest_report = manifest.get("validation_report")
    if not isinstance(manifest_report, dict) or manifest_report.get("passed") is not True:
        failures.append("manifest does not record a passing validation result")

    if not isinstance(spec, dict):
        failures.append("label-spec.json must contain an object")
        return
    try:
        LabelSpec.from_dict(spec, artwork_path.parent)
    except (TypeError, ValueError) as error:
        failures.append(f"label-spec.json is invalid: {error}")
        return

    if spec.get("artwork") != artwork_path.name:
        failures.append("label-spec.json artwork does not match packaged artwork")

    if manifest.get("spec") != spec:
        failures.append("manifest specification does not match label-spec.json")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


# Backward-compatible private alias.
_sha256 = sha256_file
