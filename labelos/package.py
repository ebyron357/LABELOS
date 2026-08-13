"""Create traceable production release packages from passing validation reports."""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import LabelSpec, Report


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
    report_path = destination / "validation-report.json"
    report_path.write_text(json.dumps(report.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    extra_manifest: dict[str, Any] = {}
    for filename, payload in (extras or {}).items():
        safe_name = Path(filename).name
        if safe_name != filename or ".." in filename or "/" in filename or "\\" in filename:
            raise ValueError(f"Unsafe package extra filename: {filename}")
        target = destination / safe_name
        if isinstance(payload, bytes):
            target.write_bytes(payload)
        elif isinstance(payload, str):
            target.write_text(payload, encoding="utf-8")
        else:
            target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        extra_manifest[safe_name] = {
            "file": safe_name,
            "sha256": sha256_file(target),
            "bytes": target.stat().st_size,
        }
    manifest = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "artwork": {
            "file": artwork_destination.name,
            "sha256": sha256_file(artwork_destination),
            "bytes": artwork_destination.stat().st_size,
        },
        "validation_report": {
            "file": report_path.name,
            "sha256": sha256_file(report_path),
            "passed": report.passed,
        },
        "extras": extra_manifest,
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
    failures = []
    for key in ("artwork", "validation_report"):
        entry = manifest.get(key, {})
        path = destination / str(entry.get("file", ""))
        if not path.is_file():
            failures.append(f"{key} file is missing: {path.name}")
        elif entry.get("sha256") != sha256_file(path):
            failures.append(f"{key} checksum mismatch: {path.name}")
    for name, entry in (manifest.get("extras") or {}).items():
        path = destination / str(entry.get("file", name))
        if not path.is_file():
            failures.append(f"extra file is missing: {path.name}")
        elif entry.get("sha256") != sha256_file(path):
            failures.append(f"extra checksum mismatch: {path.name}")
    return failures


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


# Backward-compatible private alias.
_sha256 = sha256_file
