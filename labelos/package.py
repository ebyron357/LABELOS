"""Create traceable production release packages from passing validation reports."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from .models import LabelSpec, Report

_PACKAGE_SCHEMA_VERSION = 1
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_RESERVED_FILENAMES = {"manifest.json", "validation-report.json", "label-spec.json"}
_SVG_DOCTYPE_RE = re.compile(r"<!DOCTYPE|<!ENTITY", re.IGNORECASE)


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
    linked_assets = _copy_svg_linked_assets(spec, report, destination)
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
        "linked_assets": linked_assets,
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

    extras = manifest.get("extras") or {}
    if extras and not isinstance(extras, dict):
        failures.append("extras manifest entry must be an object")
    else:
        for name, entry in extras.items():
            extra_path = _validate_entry(destination, f"extra:{name}", entry, failures)
            if extra_path is not None and not _is_package_filename(str(entry.get("file", name))):
                failures.append(f"extra file path is invalid: {name}")

    if not any(failure.startswith("artwork ") for failure in failures):
        _validate_linked_assets(manifest, entries.get("artwork"), destination, failures)
    _validate_report_and_spec(manifest, entries, failures)
    return failures


def _assert_package_filename(filename: str, extra: bool = False) -> None:
    if not _is_package_filename(filename):
        raise ValueError(f"Unsafe package extra filename: {filename}")
    if extra and filename in _RESERVED_FILENAMES:
        raise ValueError(f"Unsafe package extra filename: {filename}")


def _manifest_entry(path: Path) -> dict[str, str | int]:
    return {"file": path.name, "sha256": sha256_file(path), "bytes": path.stat().st_size}


def _linked_manifest_entry(path: Path, destination: Path) -> dict[str, str | int]:
    entry = _manifest_entry(path)
    entry["file"] = path.relative_to(destination).as_posix()
    return entry


def _is_regular_file(path: Path) -> bool:
    return path.is_file() and not path.is_symlink()


def _is_package_filename(value: str) -> bool:
    path = Path(value)
    return path.name == value and value not in {"", ".", ".."} and not path.is_absolute()


def _is_package_relative_path(value: str) -> bool:
    path = Path(value)
    return bool(value) and not path.is_absolute() and all(part not in {"", ".", ".."} for part in path.parts)


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


def _copy_svg_linked_assets(spec: LabelSpec, report: Report, destination: Path) -> dict[str, dict[str, str | int]]:
    """Copy validated external SVG raster dependencies into the release package."""

    if spec.artwork.suffix.lower() != ".svg":
        return {}
    assets = report.metadata.get("svg_linked_images", [])
    if not isinstance(assets, list):
        raise TypeError("Validation report has invalid linked SVG asset metadata")
    manifest_assets: dict[str, dict[str, str | int]] = {}
    for asset in assets:
        if not isinstance(asset, dict) or not isinstance(asset.get("source"), str):
            raise TypeError("Validation report has invalid linked SVG asset metadata")
        source = _svg_linked_asset_path(spec.artwork, asset["source"])
        target = destination / asset["source"]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        manifest_assets[asset["source"]] = _linked_manifest_entry(target, destination)
    return manifest_assets


def _svg_linked_asset_path(artwork: Path, href: str) -> Path:
    if not href or "://" in href or href.startswith(("/", "\\")) or "#" in href or "?" in href:
        raise ValueError("SVG linked raster path must be a local relative file")
    relative = Path(href.replace("\\", "/"))
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
        raise ValueError("SVG linked raster path must be a local relative file")
    root = artwork.parent.resolve()
    unresolved = root / relative
    candidate = unresolved.resolve()
    try:
        candidate.relative_to(root)
    except ValueError as error:
        raise ValueError("SVG linked raster path escapes the artwork directory") from error
    if any(part.is_symlink() for part in (unresolved, *unresolved.parents)) or not candidate.is_file():
        raise ValueError("SVG linked raster path must reference a regular file")
    return candidate


def _svg_linked_image_hrefs(artwork: Path) -> set[str]:
    try:
        text = artwork.read_text(encoding="utf-8")
    except OSError as error:
        raise ValueError(f"could not read SVG artwork: {error}") from error
    if _SVG_DOCTYPE_RE.search(text):
        raise ValueError("SVG contains a DOCTYPE or entity declaration")
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError as error:
        raise ValueError(f"SVG is invalid XML: {error}") from error
    hrefs = set()
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1] != "image":
            continue
        href = element.get("href") or element.get("{http://www.w3.org/1999/xlink}href")
        if href and not href.startswith("data:image/"):
            normalized_href = href.replace("\\", "/")
            if (
                "://" in href
                or href.startswith(("/", "\\"))
                or "#" in href
                or "?" in href
                or not _is_package_relative_path(normalized_href)
            ):
                raise ValueError("SVG image href must be a local relative file path")
            hrefs.add(Path(normalized_href).as_posix())
    return hrefs


def _validate_linked_assets(
    manifest: dict[str, Any], artwork_path: Path | None, destination: Path, failures: list[str]
) -> None:
    linked_assets = manifest.get("linked_assets") or {}
    if not isinstance(linked_assets, dict):
        failures.append("linked_assets manifest entry must be an object")
        return
    if artwork_path is None or artwork_path.suffix.lower() != ".svg":
        if linked_assets:
            failures.append("non-SVG package must not contain linked SVG assets")
        return
    try:
        expected_hrefs = _svg_linked_image_hrefs(artwork_path)
    except ValueError as error:
        failures.append(f"packaged SVG linked asset references are invalid: {error}")
        return
    if set(linked_assets) != expected_hrefs:
        failures.append("linked_assets manifest does not match SVG image references")
    for href, entry in linked_assets.items():
        if not isinstance(href, str) or not _is_package_relative_path(href):
            failures.append(f"linked SVG asset path is invalid: {href!r}")
            continue
        if not isinstance(entry, dict) or entry.get("file") != href:
            failures.append(f"linked SVG asset manifest file is invalid: {href}")
            continue
        _validate_linked_entry(destination, href, entry, failures)


def _validate_linked_entry(
    destination: Path, href: str, entry: dict[str, Any], failures: list[str]
) -> None:
    filename = entry.get("file")
    if not isinstance(filename, str) or not _is_package_relative_path(filename):
        failures.append(f"linked SVG asset file is invalid: {href}")
        return
    path = destination / filename
    if not _is_regular_file(path):
        failures.append(f"linked SVG asset is missing or is not a regular file: {href}")
        return
    digest = entry.get("sha256")
    if not isinstance(digest, str) or _SHA256_RE.fullmatch(digest) is None:
        failures.append(f"linked SVG asset sha256 is invalid: {href}")
    elif digest != sha256_file(path):
        failures.append(f"linked SVG asset checksum mismatch: {href}")
    byte_count = entry.get("bytes")
    if not isinstance(byte_count, int) or isinstance(byte_count, bool) or byte_count != path.stat().st_size:
        failures.append(f"linked SVG asset byte count mismatch: {href}")


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
