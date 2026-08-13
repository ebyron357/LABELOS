"""Create traceable production release packages from passing validation reports."""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from .evidence import BLOCKED_REQUIREMENTS
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
        "blocked_requirements": list(BLOCKED_REQUIREMENTS),
    }
    if spec.native_evidence is not None:
        manifest["native_evidence"] = _copy_native_evidence(spec, destination)
    manifest_path = destination / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest_path


def _copy_native_evidence(spec: LabelSpec, destination: Path) -> dict[str, dict[str, object]]:
    """Copy native build proof artifacts into the package and return their checksums."""
    evidence_dir = destination / "native-evidence"
    evidence_dir.mkdir()
    entries: dict[str, dict[str, object]] = {}
    for name, source in spec.native_evidence.artifacts().items():
        copied = evidence_dir / source.name
        shutil.copy2(source, copied)
        entries[name] = {
            "file": f"{evidence_dir.name}/{copied.name}",
            "sha256": _sha256(copied),
            "bytes": copied.stat().st_size,
        }
    return entries


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
        elif entry.get("sha256") != _sha256(path):
            failures.append(f"{key} checksum mismatch: {path.name}")
    native_evidence = manifest.get("native_evidence") or {}
    if not isinstance(native_evidence, dict):
        return failures + ["manifest.json native_evidence must be an object"]
    for key, entry in sorted(native_evidence.items()):
        if not isinstance(entry, dict):
            failures.append(f"native evidence {key} entry is malformed")
            continue
        path = destination / str(entry.get("file", ""))
        if not path.is_file():
            failures.append(f"native evidence {key} file is missing: {path.name}")
        elif entry.get("sha256") != _sha256(path):
            failures.append(f"native evidence {key} checksum mismatch: {path.name}")
    return failures


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
