"""Native-build evidence gate.

Evidence is only accepted when it is present, readable, well formed, and positively
proves what it claims. Every other outcome — absent, unreadable, malformed, partial,
ambiguous, or reached through an unsafe path — is an error. The gate never infers a
pass from the absence of a recorded failure.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from .models import NATIVE_EVIDENCE_ARTIFACTS, LabelSpec, NativeEvidenceSpec, Report

CHECK_NAME = "native-evidence"


def validate_native_evidence(spec: LabelSpec, report: Report) -> None:
    """Record native-build evidence findings on ``report``. Configured but unproven fails."""
    evidence = spec.native_evidence
    if evidence is None:
        return
    report.checks.append(CHECK_NAME)
    artifacts: dict[str, Path] = {}
    for role in NATIVE_EVIDENCE_ARTIFACTS:
        path = _resolve_role(evidence, role, report)
        if path is not None:
            artifacts[role] = path
    report.metadata["native_evidence"] = {
        "artifacts": {
            role: {
                "file": path.name,
                "sha256": sha256_file(path),
                "bytes": path.stat().st_size,
            }
            for role, path in sorted(artifacts.items())
        },
        "required_layers": list(evidence.required_layers),
        "required_objects": list(evidence.required_objects),
    }
    if "evidence_json" in artifacts:
        _check_evidence_json(artifacts["evidence_json"], evidence, report)
    if "log" in artifacts:
        _check_log(artifacts["log"], report)


def resolve_artifact(evidence: NativeEvidenceSpec, role: str) -> Path:
    """Return the validated source path for ``role`` or raise. Used when packaging."""
    declared = getattr(evidence, role)
    if declared is None:
        raise ValueError(f"native_evidence.{role} is not declared")
    path, problem = safe_relative_path(evidence.root, declared)
    if path is None:
        raise ValueError(f"native_evidence.{role} path is unsafe: {problem}")
    if not path.is_file():
        raise ValueError(f"native_evidence.{role} file does not exist: {path}")
    return path


def safe_relative_path(root: Path, declared: Any) -> tuple[Path | None, str | None]:
    """Resolve ``declared`` under ``root``, refusing absolute, escaping, or linked paths."""
    if not isinstance(declared, str) or not declared.strip():
        return None, "path must be a non-empty string"
    candidate = Path(declared)
    if candidate.is_absolute() or candidate.anchor:
        return None, "path must be relative to its package or configuration directory"
    if any(part == ".." for part in candidate.parts):
        return None, "path must not traverse parent directories"
    real_root = Path(os.path.realpath(root))
    normalized = Path(os.path.normpath(real_root / candidate))
    if normalized == real_root or not normalized.is_relative_to(real_root):
        return None, "path escapes its package or configuration directory"
    if Path(os.path.realpath(normalized)) != normalized:
        return None, "path resolves through a symbolic link"
    return normalized, None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_role(evidence: NativeEvidenceSpec, role: str, report: Report) -> Path | None:
    declared = getattr(evidence, role)
    if declared is None:
        report.add(
            "EVIDENCE_ARTIFACT_MISSING",
            "error",
            f"native_evidence.{role} is not declared",
        )
        return None
    path, problem = safe_relative_path(evidence.root, declared)
    if path is None:
        report.add(
            "EVIDENCE_PATH_UNSAFE",
            "error",
            f"native_evidence.{role}: {problem}",
            declared,
        )
        return None
    if not path.is_file():
        report.add(
            "EVIDENCE_ARTIFACT_MISSING",
            "error",
            f"native_evidence.{role} file does not exist",
            str(path),
        )
        return None
    return path


def _check_evidence_json(path: Path, evidence: NativeEvidenceSpec, report: Report) -> None:
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        report.add("EVIDENCE_INVALID_JSON", "error", f"Evidence JSON is unreadable: {error}", str(path))
        return
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as error:
        report.add("EVIDENCE_INVALID_JSON", "error", f"Evidence JSON is malformed: {error}", str(path))
        return
    if not isinstance(data, dict):
        report.add("EVIDENCE_INVALID_JSON", "error", "Evidence JSON root must be an object", str(path))
        return
    _check_layers(data, evidence, report, path)
    _check_objects(data, evidence, report, path)
    if data.get("reopened_without_repair") is not True:
        report.add(
            "NATIVE_REOPEN_UNPROVEN",
            "error",
            "Evidence JSON does not set reopened_without_repair to boolean true",
            str(path),
        )


def _check_layers(
    data: dict[str, Any], evidence: NativeEvidenceSpec, report: Report, path: Path
) -> None:
    if "missing_layers" not in data:
        report.add(
            "NATIVE_LAYERS_MISSING",
            "error",
            "Evidence JSON does not report missing_layers",
            str(path),
        )
    else:
        value = data["missing_layers"]
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            report.add(
                "NATIVE_LAYERS_MISSING",
                "error",
                "Evidence JSON missing_layers must be a list of layer names",
                str(path),
            )
        elif value:
            report.add(
                "NATIVE_LAYERS_MISSING",
                "error",
                f"Native build reports missing layers: {', '.join(sorted(value))}",
                str(path),
            )
    if not evidence.required_layers:
        return
    present = _positive_names(data.get("layers"))
    if present is None:
        report.add(
            "NATIVE_LAYERS_MISSING",
            "error",
            "Evidence JSON does not positively list the layers present in the native build",
            str(path),
        )
        return
    absent = [name for name in evidence.required_layers if name not in present]
    if absent:
        report.add(
            "NATIVE_LAYERS_MISSING",
            "error",
            f"Required layers are not confirmed present: {', '.join(absent)}",
            str(path),
        )


def _check_objects(
    data: dict[str, Any], evidence: NativeEvidenceSpec, report: Report, path: Path
) -> None:
    if not evidence.required_objects:
        return
    present = _positive_names(data.get("objects"))
    if present is None:
        report.add(
            "NAMED_OBJECTS_MISSING",
            "error",
            "Evidence JSON does not positively list the named objects in the native build",
            str(path),
        )
        return
    absent = [name for name in evidence.required_objects if name not in present]
    if absent:
        report.add(
            "NAMED_OBJECTS_MISSING",
            "error",
            f"Required named objects are not confirmed present: {', '.join(absent)}",
            str(path),
        )


def _positive_names(value: Any) -> set[str] | None:
    """Return positively confirmed names, or None when the claim is absent or malformed."""
    if isinstance(value, list):
        if not all(isinstance(item, str) and item for item in value):
            return None
        return set(value)
    if isinstance(value, dict):
        names = set()
        for key, flag in value.items():
            if not isinstance(key, str) or not key or not isinstance(flag, bool):
                return None
            if flag is True:
                names.add(key)
        return names
    return None


def _check_log(path: Path, report: Report) -> None:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as error:
        report.add(
            "EVIDENCE_LOG_NOT_PASSED",
            "error",
            f"Evidence log is unreadable: {error}",
            str(path),
        )
        return
    final = ""
    for line in reversed(text.splitlines()):
        if line.strip():
            final = line.strip()
            break
    if final != "PASSED":
        report.add(
            "EVIDENCE_LOG_NOT_PASSED",
            "error",
            f"Evidence log does not end with PASSED (final non-empty line: {final!r})",
            str(path),
        )
