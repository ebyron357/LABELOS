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
from .validate import svg_linked_rasters

_PACKAGE_SCHEMA_VERSION = 2
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
    if report.metadata.get("artwork_sha256") != sha256_file(spec.artwork):
        raise ValueError("Artwork changed after validation; validate again before packaging")
    linked_sources = svg_linked_rasters(spec.artwork) if spec.artwork.suffix.lower() == ".svg" else []
    validated_assets = {
        item["href"]: item["sha256"]
        for item in report.metadata.get("svg_linked_images", [])
        if isinstance(item, dict)
        and isinstance(item.get("href"), str)
        and isinstance(item.get("sha256"), str)
    }
    if linked_sources and {
        asset.href: sha256_file(asset.path) for asset in linked_sources
    } != validated_assets:
        raise ValueError("Linked SVG assets changed after validation; validate again before packaging")
    destination = destination.resolve()
    if destination.exists():
        raise FileExistsError(f"Package destination already exists: {destination}")
    destination.mkdir(parents=True)
    artwork_destination = destination / spec.artwork.name
    shutil.copy2(spec.artwork, artwork_destination)
    linked_assets: dict[str, Any] = {}
    for asset in linked_sources:
        asset_destination = destination / asset.href
        asset_destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(asset.path, asset_destination)
        linked_assets[asset.href] = _manifest_entry(asset_destination, destination)
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
        "schema_version": _PACKAGE_SCHEMA_VERSION if linked_assets else 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "artwork": _manifest_entry(artwork_destination),
        "validation_report": {**_manifest_entry(report_path), "passed": report.passed},
        "label_spec": _manifest_entry(spec_path),
        "extras": extra_manifest,
        "spec": spec_payload,
    }
    if linked_assets:
        manifest["linked_assets"] = linked_assets
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
    if schema_version not in {1, _PACKAGE_SCHEMA_VERSION}:
        failures.append(f"unsupported manifest schema version: {manifest.get('schema_version')!r}")

    entries: dict[str, Path] = {}
    for key in ("artwork", "validation_report", "label_spec"):
        path = _validate_entry(destination, key, manifest.get(key), failures)
        if path is not None:
            entries[key] = path

    extras = manifest.get("extras") or {}
    if extras and not isinstance(extras, dict):
        failures.append("extras manifest entry must be an object")
    else:
        for name, entry in extras.items():
            extra_path = _validate_entry(destination, f"extra:{name}", entry, failures)
            if extra_path is not None and not _is_package_filename(str(entry.get("file", name))):
                failures.append(f"extra file path is invalid: {name}")

    _validate_report_and_spec(manifest, entries, failures)
    if schema_version == _PACKAGE_SCHEMA_VERSION:
        _validate_linked_assets(manifest, entries, failures)
    return failures


def _assert_package_filename(filename: str, extra: bool = False) -> None:
    if not _is_package_filename(filename):
        raise ValueError(f"Unsafe package extra filename: {filename}")
    if extra and filename in _RESERVED_FILENAMES:
        raise ValueError(f"Unsafe package extra filename: {filename}")


def _manifest_entry(path: Path, root: Path | None = None) -> dict[str, str | int]:
    filename = path.relative_to(root).as_posix() if root is not None else path.name
    return {"file": filename, "sha256": sha256_file(path), "bytes": path.stat().st_size}


def _is_regular_file(path: Path, root: Path | None = None) -> bool:
    if not path.is_file() or path.is_symlink():
        return False
    if root is None:
        return True
    current = path
    while current != root:
        if current.is_symlink():
            return False
        current = current.parent
    return True


def _is_package_filename(value: str, allow_nested: bool = False) -> bool:
    path = Path(value)
    return (
        bool(value)
        and value not in {".", ".."}
        and not path.is_absolute()
        and "\\" not in value
        and ".." not in path.parts
        and (allow_nested or path.name == value)
    )


def _validate_entry(destination: Path, key: str, entry: Any, failures: list[str]) -> Path | None:
    if not isinstance(entry, dict):
        failures.append(f"{key} manifest entry is missing or invalid")
        return None

    filename = entry.get("file")
    allow_nested = key.startswith("linked asset:")
    if not isinstance(filename, str) or not _is_package_filename(filename, allow_nested=allow_nested):
        failures.append(f"{key} file must be a package-relative filename")
        return None

    path = destination / filename
    if not _is_regular_file(path, destination):
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


def _validate_linked_assets(manifest: dict[str, Any], entries: dict[str, Path], failures: list[str]) -> None:
    artwork_path = entries.get("artwork")
    if artwork_path is None or artwork_path.suffix.lower() != ".svg":
        failures.append("schema-2 package artwork must be SVG")
        return
    linked_assets = manifest.get("linked_assets")
    if not isinstance(linked_assets, dict):
        failures.append("linked_assets manifest entry must be an object")
        return
    artwork_entry = manifest.get("artwork")
    if isinstance(artwork_entry, dict) and artwork_entry.get("sha256") != sha256_file(artwork_path):
        return
    try:
        expected = {asset.href for asset in svg_linked_rasters(artwork_path)}
    except ValueError as error:
        failures.append(f"packaged SVG linked assets are invalid: {error}")
        return
    if set(linked_assets) != expected:
        failures.append("linked_assets manifest does not match packaged SVG references")
    for href, entry in linked_assets.items():
        if not isinstance(href, str) or not _is_package_filename(href, allow_nested=True):
            failures.append(f"linked asset path is invalid: {href!r}")
            continue
        _validate_entry(artwork_path.parent, f"linked asset:{href}", entry, failures)
        if isinstance(entry, dict) and entry.get("file") != href:
            failures.append(f"linked asset manifest file does not match SVG reference: {href}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


# Backward-compatible private alias.
_sha256 = sha256_file
