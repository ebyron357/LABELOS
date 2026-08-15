"""Native-build evidence gate.

LABELOS records and verifies operator-supplied evidence that a native application
build produced the artwork. It never synthesises that evidence. Every check here
fails closed: absent, unreadable, incomplete, or unsafe evidence is an error on the
label report, and an errored report blocks packaging.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .models import ARTIFACT_KEYS, REQUIRED_ARTIFACT_KEYS, LabelSpec, NativeEvidenceSpec, Report

PASS_TOKEN = "PASSED"


def check_native_evidence(spec: LabelSpec, report: Report) -> None:
    """Record native-evidence findings on ``report``. No block configured is a no-op."""
    evidence = spec.native_evidence
    if evidence is None:
        return
    report.checks.append("native-evidence")
    artifacts = _run_gate(evidence, report)
    report.metadata["native_evidence"] = {
        "artifacts": {key: path.name for key, path in sorted(artifacts.items())},
        "required_layers": list(evidence.required_layers),
        "required_objects": list(evidence.required_objects),
    }


def _run_gate(evidence: NativeEvidenceSpec, report: Report) -> dict[str, Path]:
    """Apply every evidence check, recording failures on ``report``."""
    artifacts = _resolve_artifacts(evidence, report)
    document = _load_evidence_json(artifacts.get("evidence_json"), report)
    if document is not None:
        _check_layers(evidence, document, report)
        _check_objects(evidence, document, report)
        _check_reopen(document, report)
    _check_log(artifacts.get("log"), report)
    return artifacts


def evidence_artifacts(spec: LabelSpec) -> dict[str, Path]:
    """Re-run the gate and return validated artifact paths for packaging.

    Packaging does not rely on the caller's report for evidence: the gate is
    applied again here, so a report that never ran it — or was constructed by
    hand — cannot smuggle unverified artifacts into a release package. Raises
    ``ValueError`` rather than returning a partial set.
    """
    evidence = spec.native_evidence
    if evidence is None:
        return {}
    probe = Report(source=str(spec.artwork))
    artifacts = _run_gate(evidence, probe)
    if not probe.passed:
        raise ValueError(
            "Refusing to package unverified native evidence: "
            + "; ".join(issue.message for issue in probe.issues if issue.severity == "error")
        )
    return artifacts


def _resolve_artifacts(evidence: NativeEvidenceSpec, report: Report) -> dict[str, Path]:
    declared = evidence.declared()
    resolved: dict[str, Path] = {}
    for key in ARTIFACT_KEYS:
        value = declared.get(key)
        if value is None:
            if key in REQUIRED_ARTIFACT_KEYS:
                report.add(
                    "EVIDENCE_ARTIFACT_MISSING",
                    "error",
                    f"native_evidence.{key} is not declared",
                )
            continue
        path = _safe_path(evidence.root, value, key, report)
        if path is None:
            continue
        if not path.is_file():
            report.add(
                "EVIDENCE_ARTIFACT_MISSING",
                "error",
                f"Native evidence artifact does not exist: {key}",
                str(path),
            )
            continue
        resolved[key] = path
    return resolved


def _safe_path(root: Path, declared: str, key: str, report: Report) -> Path | None:
    """Resolve ``declared`` under ``root``, rejecting escapes and symlinks."""
    candidate = Path(declared)
    if candidate.is_absolute():
        report.add(
            "EVIDENCE_PATH_UNSAFE",
            "error",
            f"native_evidence.{key} must be relative to the configuration directory",
            declared,
        )
        return None
    real_root = Path(os.path.realpath(root))
    expected = Path(os.path.normpath(real_root / candidate))
    if real_root not in expected.parents:
        report.add(
            "EVIDENCE_PATH_UNSAFE",
            "error",
            f"native_evidence.{key} escapes the configuration directory",
            declared,
        )
        return None
    if Path(os.path.realpath(expected)) != expected:
        report.add(
            "EVIDENCE_PATH_UNSAFE",
            "error",
            f"native_evidence.{key} resolves through a symlink",
            declared,
        )
        return None
    return expected


def _load_evidence_json(path: Path | None, report: Report) -> dict[str, Any] | None:
    if path is None:
        return None
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        report.add(
            "EVIDENCE_INVALID_JSON",
            "error",
            f"Native evidence JSON is unreadable or malformed: {error}",
            str(path),
        )
        return None
    if not isinstance(document, dict):
        report.add(
            "EVIDENCE_INVALID_JSON",
            "error",
            "Native evidence JSON root must be a JSON object",
            str(path),
        )
        return None
    return document


def _check_layers(evidence: NativeEvidenceSpec, document: dict[str, Any], report: Report) -> None:
    missing = document.get("missing_layers")
    if not isinstance(missing, list):
        report.add(
            "NATIVE_LAYERS_MISSING",
            "error",
            "Native evidence must report missing_layers as a list",
        )
    elif missing:
        report.add(
            "NATIVE_LAYERS_MISSING",
            "error",
            f"Native build reports missing layers: {', '.join(str(item) for item in missing)}",
        )
    if not evidence.required_layers:
        return
    present = document.get("layers")
    if not isinstance(present, list):
        report.add(
            "NATIVE_LAYERS_MISSING",
            "error",
            "Native evidence must list confirmed layers in 'layers' when layers are required",
        )
        return
    confirmed = {value for value in present if isinstance(value, str)}
    for layer in evidence.required_layers:
        if layer not in confirmed:
            report.add(
                "NATIVE_LAYERS_MISSING",
                "error",
                f"Required layer is not positively confirmed present: {layer!r}",
            )


def _check_objects(evidence: NativeEvidenceSpec, document: dict[str, Any], report: Report) -> None:
    if not evidence.required_objects:
        return
    named = document.get("named_objects")
    if not isinstance(named, list):
        report.add(
            "NAMED_OBJECTS_MISSING",
            "error",
            "Native evidence must list confirmed named_objects as a list",
        )
        return
    confirmed = {value for value in named if isinstance(value, str)}
    for name in evidence.required_objects:
        if name not in confirmed:
            report.add(
                "NAMED_OBJECTS_MISSING",
                "error",
                f"Required named object is not confirmed present: {name!r}",
            )


def _check_reopen(document: dict[str, Any], report: Report) -> None:
    if document.get("reopened_without_repair") is not True:
        report.add(
            "NATIVE_REOPEN_UNPROVEN",
            "error",
            "Native evidence must set reopened_without_repair to boolean true",
        )


def _check_log(path: Path | None, report: Report) -> None:
    if path is None:
        return
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        report.add(
            "EVIDENCE_LOG_NOT_PASSED",
            "error",
            f"Native evidence log is unreadable: {error}",
            str(path),
        )
        return
    final = next((line for line in reversed(text.splitlines()) if line.strip()), None)
    if final is None or final.strip() != PASS_TOKEN:
        report.add(
            "EVIDENCE_LOG_NOT_PASSED",
            "error",
            f"Final non-empty log line is {final if final is None else final.strip()!r}; "
            f"expected {PASS_TOKEN!r}",
            str(path),
        )
