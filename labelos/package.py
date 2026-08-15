"""Create traceable production release packages from passing validation reports."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

from .evidence import evidence_artifacts
from .models import LabelSpec, Report

EVIDENCE_DIRECTORY = "native-evidence"

#: External approvals LABELOS cannot grant. Recorded on every manifest and
#: re-checked by :func:`verify_package`; a passing evidence gate never clears them.
BLOCKED_REQUIREMENTS = (
    "icc_profile",
    "printer_profile",
    "production_pdf",
    "regulatory_approval",
)


def create_package(spec: LabelSpec, report: Report, destination: Path) -> Path:
    """Create an immutable-style package directory and return its manifest path."""
    if not report.passed:
        raise ValueError("Refusing to package artwork with validation errors")
    # Resolve evidence before anything is written so an unverifiable set cannot
    # leave a partially populated package behind.
    artifacts = evidence_artifacts(spec)
    _reject_name_collisions(artifacts)
    destination = destination.resolve()
    if destination.exists():
        raise FileExistsError(f"Package destination already exists: {destination}")
    destination.mkdir(parents=True)
    artwork_destination = destination / spec.artwork.name
    shutil.copy2(spec.artwork, artwork_destination)
    report_path = destination / "validation-report.json"
    report_path.write_text(
        json.dumps(report.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    manifest = {
        "schema_version": 2,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "artwork": {
            "file": artwork_destination.name,
            "sha256": _sha256(artwork_destination),
            "bytes": artwork_destination.stat().st_size,
        },
        "validation_report": {
            "file": report_path.name,
            "sha256": _sha256(report_path),
            "bytes": report_path.stat().st_size,
            "passed": report.passed,
        },
        "native_evidence": _copy_evidence(artifacts, destination),
        "blocked_requirements": list(BLOCKED_REQUIREMENTS),
        "spec": report.metadata.get("spec", {}),
    }
    manifest_path = destination / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest_path


def _reject_name_collisions(artifacts: dict[str, Path]) -> None:
    """Two artifacts sharing a file name would overwrite each other once copied."""
    seen: dict[str, list[str]] = {}
    for key, path in sorted(artifacts.items()):
        seen.setdefault(path.name, []).append(key)
    collisions = sorted(name for name, keys in seen.items() if len(keys) > 1)
    if collisions:
        raise ValueError(
            f"Native evidence artifacts share file names: {', '.join(collisions)}"
        )


def _copy_evidence(artifacts: dict[str, Path], destination: Path) -> dict[str, dict]:
    """Copy evidence into the package and hash the copied bytes, not the sources."""
    if not artifacts:
        return {}
    evidence_directory = destination / EVIDENCE_DIRECTORY
    evidence_directory.mkdir()
    recorded: dict[str, dict] = {}
    for key, source in sorted(artifacts.items()):
        packaged = evidence_directory / source.name
        shutil.copy2(source, packaged)
        recorded[key] = {
            "file": f"{EVIDENCE_DIRECTORY}/{packaged.name}",
            "sha256": _sha256(packaged),
            "bytes": packaged.stat().st_size,
        }
    return recorded


def verify_package(destination: Path) -> list[str]:
    """Return integrity failures for a release package.

    Every hash is recomputed from the bytes actually present in the package; the
    manifest is treated as a claim to be checked, never as a source of truth.
    """
    manifest_path = destination / "manifest.json"
    if not manifest_path.is_file():
        return ["manifest.json is missing"]
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        return [f"manifest.json is invalid JSON: {error}"]
    if not isinstance(manifest, dict):
        return ["manifest.json root must be a JSON object"]
    failures = []
    for key in ("artwork", "validation_report"):
        failures.extend(_verify_entry(destination, key, manifest.get(key)))
    failures.extend(_verify_evidence(destination, manifest.get("native_evidence", {})))
    failures.extend(_verify_blocked_requirements(manifest.get("blocked_requirements")))
    return failures


def _verify_evidence(destination: Path, recorded: object) -> list[str]:
    if not isinstance(recorded, dict):
        return ["native_evidence must be a JSON object"]
    failures = []
    for key in sorted(recorded):
        failures.extend(
            _verify_entry(destination, f"native_evidence.{key}", recorded[key])
        )
    evidence_directory = destination / EVIDENCE_DIRECTORY
    if not evidence_directory.is_dir():
        if recorded:
            failures.append(f"{EVIDENCE_DIRECTORY} directory is missing")
        return failures
    listed = {
        str(entry.get("file", "")) for entry in recorded.values() if isinstance(entry, dict)
    }
    for path in sorted(evidence_directory.rglob("*")):
        if path.is_dir():
            continue
        relative = path.relative_to(destination).as_posix()
        if relative not in listed:
            failures.append(f"{EVIDENCE_DIRECTORY} contains an unrecorded file: {relative}")
    return failures


def _verify_blocked_requirements(recorded: object) -> list[str]:
    if not isinstance(recorded, list) or sorted(
        str(value) for value in recorded
    ) != sorted(BLOCKED_REQUIREMENTS):
        return [
            "blocked_requirements must record every external blocker: "
            + ", ".join(BLOCKED_REQUIREMENTS)
        ]
    return []


def _verify_entry(destination: Path, label: str, entry: object) -> list[str]:
    if not isinstance(entry, dict):
        return [f"{label} manifest entry is missing or malformed"]
    name = str(entry.get("file", ""))
    path = _packaged_path(destination, name)
    if path is None:
        return [f"{label} manifest entry has an unsafe file path: {name}"]
    if not path.is_file():
        return [f"{label} file is missing: {name}"]
    if entry.get("sha256") != _sha256(path):
        return [f"{label} checksum mismatch: {name}"]
    # Only reported when the bytes themselves are intact, so a tampered file
    # yields one unambiguous checksum failure rather than two overlapping ones.
    if "bytes" in entry and entry.get("bytes") != path.stat().st_size:
        return [f"{label} byte count mismatch: {name}"]
    return []


def _packaged_path(destination: Path, name: str) -> Path | None:
    """Resolve a manifest-declared file inside the package, or None if unsafe."""
    if not name or Path(name).is_absolute():
        return None
    real_root = Path(os.path.realpath(destination))
    expected = Path(os.path.normpath(real_root / name))
    if real_root not in expected.parents:
        return None
    if Path(os.path.realpath(expected)) != expected:
        return None
    return expected


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
