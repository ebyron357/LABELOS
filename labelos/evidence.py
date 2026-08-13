"""Native-artwork build evidence gate.

Illustrator builders (for example ``BravoPaws_Bacon_Tincture_Build.jsx``) emit a JSON
evidence file, a run log, a preview PNG, and the native ``.ai`` document. This module
verifies that bundle. It never inspects Illustrator itself: it only accepts or rejects
the evidence an operator captured from a real run.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .models import Report

#: Requirements that no software check in this repository can satisfy.
BLOCKED_REQUIREMENTS = (
    "printer_profile",
    "icc_profile",
    "regulatory_approval",
    "production_pdf",
)


@dataclass(frozen=True)
class NativeEvidence:
    """Paths and expectations for one native Illustrator build."""

    evidence_json: Path
    log: Path
    preview_png: Path
    native_artwork: Path
    required_layers: tuple[str, ...] = ()
    required_objects: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, data: dict[str, Any], root: Path) -> NativeEvidence:
        if not isinstance(data, dict):
            raise TypeError("native_evidence must be a JSON object")
        required = ("evidence_json", "log", "preview_png", "native_artwork")
        absent = [key for key in required if key not in data]
        if absent:
            raise ValueError(f"Missing required native_evidence fields: {', '.join(absent)}")
        paths = {key: (root / str(data[key])).resolve() for key in required}
        return cls(
            required_layers=_string_tuple(data.get("required_layers", ()), "required_layers"),
            required_objects=_string_tuple(data.get("required_objects", ()), "required_objects"),
            **paths,
        )

    def artifacts(self) -> dict[str, Path]:
        return {
            "evidence_json": self.evidence_json,
            "log": self.log,
            "preview_png": self.preview_png,
            "native_artwork": self.native_artwork,
        }


def _string_tuple(value: Any, field: str) -> tuple[str, ...]:
    if isinstance(value, str) or not isinstance(value, (list, tuple)):
        raise TypeError(f"{field} must be a list of strings")
    items = tuple(str(item) for item in value)
    if any(not item for item in items):
        raise ValueError(f"{field} entries cannot be empty")
    return items


def validate_native_evidence(evidence: NativeEvidence, report: Report) -> None:
    """Add gate results for a native build evidence bundle to ``report``."""
    report.checks.append("native-build-evidence")
    for name, path in evidence.artifacts().items():
        if not path.is_file():
            report.add("EVIDENCE_ARTIFACT_MISSING", "error", f"Missing {name}: {path.name}", str(path))
    if not evidence.evidence_json.is_file():
        return

    try:
        data = json.loads(evidence.evidence_json.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        report.add("EVIDENCE_INVALID_JSON", "error", f"Evidence JSON is unreadable: {error}")
        return
    if not isinstance(data, dict):
        report.add("EVIDENCE_INVALID_JSON", "error", "Evidence JSON root must be an object")
        return

    _check_missing_layers(data, report)
    _check_layers(evidence, data, report)
    _check_objects(evidence, data, report)
    _check_reopen(data, report)
    if evidence.log.is_file():
        _check_log(evidence, report)
    report.metadata["native_evidence"] = {
        "layers": _names(data.get("layers")),
        "objects": _names(data.get("objects")),
        "missing_layers": _names(data.get("missing_layers")),
        "reopened_without_repair": data.get("reopened_without_repair"),
        "blocked": list(BLOCKED_REQUIREMENTS),
    }


def _check_missing_layers(data: dict[str, Any], report: Report) -> None:
    if "missing_layers" not in data:
        report.add("EVIDENCE_INCOMPLETE", "error", "Evidence JSON has no missing_layers field")
        return
    missing = _names(data.get("missing_layers"))
    if missing:
        report.add(
            "NATIVE_LAYERS_MISSING",
            "error",
            f"Builder reported missing layers: {', '.join(missing)}",
        )


def _check_layers(evidence: NativeEvidence, data: dict[str, Any], report: Report) -> None:
    if not evidence.required_layers:
        return
    present = set(_names(data.get("layers")))
    absent = [name for name in evidence.required_layers if name not in present]
    if absent:
        report.add(
            "NATIVE_LAYERS_MISSING",
            "error",
            f"Native layers absent from evidence: {', '.join(absent)}",
        )


def _check_objects(evidence: NativeEvidence, data: dict[str, Any], report: Report) -> None:
    if not evidence.required_objects:
        return
    present = set(_names(data.get("objects")))
    absent = [name for name in evidence.required_objects if name not in present]
    if absent:
        report.add(
            "NAMED_OBJECTS_MISSING",
            "error",
            f"Required named objects absent from evidence: {', '.join(absent)}",
        )


def _check_reopen(data: dict[str, Any], report: Report) -> None:
    if data.get("reopened_without_repair") is not True:
        report.add(
            "NATIVE_REOPEN_UNPROVEN",
            "error",
            "Evidence does not prove the AI file reopened without repair",
        )


def _check_log(evidence: NativeEvidence, report: Report) -> None:
    lines = [
        line.strip()
        for line in evidence.log.read_text(encoding="utf-8", errors="replace").splitlines()
        if line.strip()
    ]
    if not lines or lines[-1] != "PASSED":
        report.add("EVIDENCE_LOG_NOT_PASSED", "error", "Build log does not end with PASSED")


def _names(value: Any) -> list[str]:
    if isinstance(value, str) or not isinstance(value, (list, tuple)):
        return []
    return [str(item) for item in value]
