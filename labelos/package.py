"""Create traceable production release packages from passing validation reports."""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .evidence import CHECK_NAME, resolve_artifact, safe_relative_path, sha256_file
from .models import NATIVE_EVIDENCE_ARTIFACTS, LabelSpec, Report

EVIDENCE_DIRNAME = "native-evidence"

#: External approvals LABELOS cannot grant. Recorded on every package, never cleared by
#: a passing native-evidence gate.
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
    if spec.native_evidence is not None and CHECK_NAME not in report.checks:
        raise ValueError("Refusing to package: the native evidence gate did not run")
    destination = destination.resolve()
    if destination.exists():
        raise FileExistsError(f"Package destination already exists: {destination}")
    destination.mkdir(parents=True)
    try:
        return _write_package(spec, report, destination)
    except BaseException:
        # Never leave a partial package behind: it would be unverifiable and would block a retry.
        shutil.rmtree(destination, ignore_errors=True)
        raise


def _write_package(spec: LabelSpec, report: Report, destination: Path) -> Path:
    artwork_destination = destination / spec.artwork.name
    shutil.copy2(spec.artwork, artwork_destination)
    evidence_entries = _package_native_evidence(spec, report, destination)
    report_path = destination / "validation-report.json"
    report_path.write_text(json.dumps(report.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest = {
        "schema_version": 2,
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
        "native_evidence": evidence_entries,
        "blocked_requirements": list(BLOCKED_REQUIREMENTS),
        "spec": report.metadata.get("spec", {}),
    }
    manifest_path = destination / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest_path


def _package_native_evidence(
    spec: LabelSpec, report: Report, destination: Path
) -> list[dict[str, Any]]:
    """Copy validated evidence into the package, hashing the packaged bytes."""
    evidence = spec.native_evidence
    if evidence is None:
        return []
    validated = (report.metadata.get("native_evidence") or {}).get("artifacts") or {}
    entries = []
    for role in NATIVE_EVIDENCE_ARTIFACTS:
        source = resolve_artifact(evidence, role)
        expected = validated.get(role, {}).get("sha256")
        if not expected:
            raise ValueError(f"Refusing to package: no validated digest for native_evidence.{role}")
        if source.is_symlink():
            raise ValueError(f"Refusing to package: native_evidence.{role} is a symbolic link")
        target_directory = destination / EVIDENCE_DIRNAME / role
        target_directory.mkdir(parents=True)
        target = target_directory / source.name
        shutil.copy2(source, target)
        digest = sha256_file(target)
        if digest != expected:
            raise ValueError(
                f"Refusing to package: native_evidence.{role} changed after validation"
            )
        entries.append(
            {
                "role": role,
                "file": f"{EVIDENCE_DIRNAME}/{role}/{source.name}",
                "sha256": digest,
                "bytes": target.stat().st_size,
            }
        )
    return entries


def verify_package(destination: Path) -> list[str]:
    """Return integrity failures for a release package, re-hashing the packaged bytes."""
    manifest_path = destination / "manifest.json"
    if not manifest_path.is_file():
        return ["manifest.json is missing"]
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        return [f"manifest.json is invalid JSON: {error}"]
    if not isinstance(manifest, dict):
        return ["manifest.json root must be an object"]
    failures = []
    for key in ("artwork", "validation_report"):
        entry = manifest.get(key) if isinstance(manifest.get(key), dict) else {}
        path, problem = safe_relative_path(destination, entry.get("file"))
        if path is None:
            failures.append(f"{key} path is unsafe: {problem}")
        elif path.is_symlink() or not path.is_file():
            failures.append(f"{key} file is missing: {path.name}")
        elif entry.get("sha256") != sha256_file(path):
            failures.append(f"{key} checksum mismatch: {path.name}")
    failures.extend(_verify_blocked_requirements(manifest))
    failures.extend(_verify_native_evidence(destination, manifest))
    return failures


def _verify_blocked_requirements(manifest: dict[str, Any]) -> list[str]:
    recorded = manifest.get("blocked_requirements")
    if (
        not isinstance(recorded, list)
        or not all(isinstance(item, str) for item in recorded)
        or sorted(recorded) != sorted(BLOCKED_REQUIREMENTS)
    ):
        return [
            "blocked_requirements must record every external blocker: "
            + ", ".join(sorted(BLOCKED_REQUIREMENTS))
        ]
    return []


def _verify_native_evidence(destination: Path, manifest: dict[str, Any]) -> list[str]:
    entries = manifest.get("native_evidence", [])
    if not isinstance(entries, list):
        return ["native_evidence must be a list of packaged evidence entries"]
    failures = []
    seen_roles: set[str] = set()
    seen_files: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            failures.append("native evidence entry is not an object")
            continue
        role = entry.get("role")
        if not isinstance(role, str) or role not in NATIVE_EVIDENCE_ARTIFACTS:
            failures.append(f"native evidence entry has an unknown role: {role!r}")
            continue
        if role in seen_roles:
            failures.append(f"native evidence role is recorded more than once: {role}")
            continue
        seen_roles.add(role)
        path, problem = safe_relative_path(destination, entry.get("file"))
        if path is None:
            failures.append(f"native evidence path for {role} is unsafe: {problem}")
            continue
        relative = path.relative_to(Path(os.path.realpath(destination))).as_posix()
        if relative in seen_files:
            failures.append(f"native evidence file is recorded more than once: {relative}")
            continue
        seen_files.add(relative)
        if path.is_symlink() or not path.is_file():
            failures.append(f"native evidence file is missing: {relative}")
            continue
        if entry.get("sha256") != sha256_file(path):
            failures.append(f"native evidence checksum mismatch: {relative}")
        elif entry.get("bytes") != path.stat().st_size:
            failures.append(f"native evidence byte count mismatch: {relative}")
    if seen_roles and seen_roles != set(NATIVE_EVIDENCE_ARTIFACTS):
        failures.append(
            "native evidence is incomplete: "
            + ", ".join(sorted(set(NATIVE_EVIDENCE_ARTIFACTS) - seen_roles))
        )
    failures.extend(_verify_no_unrecorded_evidence(destination, seen_files))
    failures.extend(_verify_manifest_matches_report(destination, entries))
    return failures


def _verify_no_unrecorded_evidence(destination: Path, seen_files: set[str]) -> list[str]:
    real_destination = Path(os.path.realpath(destination))
    evidence_directory = real_destination / EVIDENCE_DIRNAME
    if not evidence_directory.is_dir():
        return []
    failures = []
    for path in sorted(evidence_directory.rglob("*")):
        relative = path.relative_to(real_destination).as_posix()
        if path.is_symlink():
            failures.append(f"native evidence path is a symbolic link: {relative}")
        elif path.is_file() and relative not in seen_files:
            failures.append(f"native evidence file is not recorded in the manifest: {relative}")
    return failures


def _verify_manifest_matches_report(
    destination: Path, entries: list[Any]
) -> list[str]:
    """Cross-check the manifest against the digests recorded in the packaged report."""
    report_path = destination / "validation-report.json"
    if not report_path.is_file():
        return []
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return ["validation-report.json is unreadable"]
    if not isinstance(report, dict):
        return ["validation-report.json root must be an object"]
    metadata = report.get("metadata")
    validated = (metadata or {}).get("native_evidence", {}) if isinstance(metadata, dict) else {}
    artifacts = validated.get("artifacts") if isinstance(validated, dict) else None
    if not isinstance(artifacts, dict):
        return []
    recorded = {
        entry.get("role"): entry.get("sha256") for entry in entries if isinstance(entry, dict)
    }
    failures = []
    for role, details in sorted(artifacts.items()):
        expected = details.get("sha256") if isinstance(details, dict) else None
        if role not in recorded:
            failures.append(f"validated native evidence is not packaged: {role}")
        elif expected != recorded[role]:
            failures.append(f"packaged native evidence does not match the validated digest: {role}")
    return failures
