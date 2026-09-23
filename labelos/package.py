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
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_RESERVED_FILENAMES = {"manifest.json", "validation-report.json", "label-spec.json"}


def _assert_validated_artwork(spec: LabelSpec, report: Report) -> None:
    expected = report.metadata.get("artwork_sha256")
    if not isinstance(expected, str) or _SHA256_RE.fullmatch(expected) is None:
        raise ValueError("Validation report does not contain an artwork checksum")
    if sha256_file(spec.artwork) != expected:
        raise ValueError("Artwork changed after validation; validate again before packaging")


def _validated_linked_assets(spec: LabelSpec, report: Report) -> list[tuple[Path, Path]]:
    records = report.metadata.get("svg_linked_images", [])
    if not isinstance(records, list):
        raise TypeError("Validation report contains invalid linked SVG asset metadata")
    assets: list[tuple[Path, Path]] = []
    seen: set[Path] = set()
    for record in records:
        if not isinstance(record, dict):
            raise TypeError("Validation report contains invalid linked SVG asset metadata")
        filename, expected = record.get("file"), record.get("sha256")
        if not isinstance(filename, str) or not _is_package_path(filename):
            raise ValueError("Validation report contains an unsafe linked SVG asset path")
        if not isinstance(expected, str) or _SHA256_RE.fullmatch(expected) is None:
            raise ValueError("Validation report contains an invalid linked SVG asset checksum")
        relative_path = Path(filename)
        if relative_path in seen:
            continue
        seen.add(relative_path)
        source = spec.artwork.parent / relative_path
        if not _is_regular_file(source):
            raise ValueError(f"Linked SVG asset is missing or is not a regular file: {filename}")
        if sha256_file(source) != expected:
            raise ValueError(f"Linked SVG asset changed after validation: {filename}")
        assets.append((source, relative_path))
    return assets


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
    _assert_validated_artwork(spec, report)
    linked_assets = _validated_linked_assets(spec, report)
    destination.mkdir(parents=True)
    artwork_destination = destination / spec.artwork.name
    shutil.copy2(spec.artwork, artwork_destination)
    asset_manifest: dict[str, Any] = {}
    for source, relative_path in linked_assets:
        target = destination / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        asset_manifest[relative_path.as_posix()] = _manifest_entry(target, relative_path.as_posix())
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
        "validation_report": {**_manifest_entry(report_path), "passed": report.passed},
        "label_spec": _manifest_entry(spec_path),
        "assets": asset_manifest,
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
    if manifest.get("schema_version") != _PACKAGE_SCHEMA_VERSION:
        failures.append(f"unsupported manifest schema version: {manifest.get('schema_version')!r}")

    entries: dict[str, Path] = {}
    for key in ("artwork", "validation_report", "label_spec"):
        path = _validate_entry(destination, key, manifest.get(key), failures)
        if path is not None:
            entries[key] = path

    _validate_assets(destination, manifest.get("assets"), failures)
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


def _manifest_entry(path: Path, filename: str | None = None) -> dict[str, str | int]:
    return {"file": filename or path.name, "sha256": sha256_file(path), "bytes": path.stat().st_size}


def _is_regular_file(path: Path) -> bool:
    return path.is_file() and not path.is_symlink()


def _is_package_filename(value: str) -> bool:
    path = Path(value)
    return path.name == value and value not in {"", ".", ".."} and not path.is_absolute()


def _is_package_path(value: str) -> bool:
    path = Path(value)
    return (
        bool(value)
        and not path.is_absolute()
        and "\\" not in value
        and all(part not in {"", ".", ".."} for part in value.split("/"))
    )


def _validate_assets(destination: Path, assets: Any, failures: list[str]) -> None:
    if assets is None:
        failures.append("assets manifest entry is missing")
        return
    if not isinstance(assets, dict):
        failures.append("assets manifest entry must be an object")
        return
    for name, entry in assets.items():
        if not isinstance(name, str) or not _is_package_path(name):
            failures.append(f"asset file path is invalid: {name}")
            continue
        if not isinstance(entry, dict) or entry.get("file") != name:
            failures.append(f"asset manifest entry does not match path: {name}")
            continue
        _validate_path_entry(destination, f"asset:{name}", entry, failures)


def _validate_entry(destination: Path, key: str, entry: Any, failures: list[str]) -> Path | None:
    if not isinstance(entry, dict):
        failures.append(f"{key} manifest entry is missing or invalid")
        return None

    filename = entry.get("file")
    if not isinstance(filename, str) or not _is_package_filename(filename):
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


def _validate_path_entry(destination: Path, key: str, entry: Any, failures: list[str]) -> Path | None:
    if not isinstance(entry, dict):
        failures.append(f"{key} manifest entry is missing or invalid")
        return None
    filename = entry.get("file")
    if not isinstance(filename, str) or not _is_package_path(filename):
        failures.append(f"{key} file must be a safe package-relative path")
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
    if not isinstance(byte_count, int) or isinstance(byte_count, bool) or byte_count != path.stat().st_size:
        failures.append(f"{key} byte count mismatch: {filename}")
    return path


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
    elif not _report_assets_match_manifest(report, manifest):
        failures.append("manifest assets do not match validated linked SVG assets")

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


def _report_assets_match_manifest(report: dict[str, Any], manifest: dict[str, Any]) -> bool:
    metadata = report.get("metadata", {})
    linked_images = metadata.get("svg_linked_images", []) if isinstance(metadata, dict) else []
    if not isinstance(linked_images, list):
        return False
    expected_assets: set[str] = set()
    for image in linked_images:
        if not isinstance(image, dict) or not isinstance(image.get("file"), str):
            return False
        expected_assets.add(image["file"])
    assets = manifest.get("assets")
    return isinstance(assets, dict) and set(assets) == expected_assets


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


# Backward-compatible private alias.
_sha256 = sha256_file
