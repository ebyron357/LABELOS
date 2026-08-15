"""Configuration and report models with dependency-free validation."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Issue:
    code: str
    severity: str
    message: str
    path: str | None = None


@dataclass
class Report:
    source: str
    checks: list[str] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return not any(issue.severity == "error" for issue in self.issues)

    def add(self, code: str, severity: str, message: str, path: str | None = None) -> None:
        self.issues.append(Issue(code, severity, message, path))

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "passed": self.passed,
            "checks": self.checks,
            "issues": [asdict(issue) for issue in self.issues],
            "metadata": self.metadata,
        }


NATIVE_EVIDENCE_ARTIFACTS = ("evidence_json", "log", "preview_png", "native_artwork")


@dataclass(frozen=True)
class NativeEvidenceSpec:
    """Declared native-build evidence. Every artifact is required once the block exists."""

    root: Path
    evidence_json: str | None = None
    log: str | None = None
    preview_png: str | None = None
    native_artwork: str | None = None
    required_layers: tuple[str, ...] = ()
    required_objects: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, data: Any, root: Path) -> NativeEvidenceSpec:
        if not isinstance(data, dict):
            raise TypeError("native_evidence must be a JSON object")
        allowed = set(NATIVE_EVIDENCE_ARTIFACTS) | {"required_layers", "required_objects"}
        unknown = sorted(set(data) - allowed)
        if unknown:
            raise ValueError(f"Unknown native_evidence fields: {', '.join(unknown)}")
        artifacts: dict[str, str | None] = {}
        for key in NATIVE_EVIDENCE_ARTIFACTS:
            if key not in data:
                artifacts[key] = None
                continue
            value = data[key]
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"native_evidence.{key} must be a non-empty string path")
            artifacts[key] = value
        return cls(
            root=root.resolve(),
            required_layers=_name_tuple(data, "required_layers"),
            required_objects=_name_tuple(data, "required_objects"),
            **artifacts,
        )


def _name_tuple(data: dict[str, Any], key: str) -> tuple[str, ...]:
    value = data.get(key, [])
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise ValueError(f"native_evidence.{key} must be a list of non-empty names")
    if len(set(value)) != len(value):
        raise ValueError(f"native_evidence.{key} must not contain duplicate names")
    return tuple(value)


@dataclass(frozen=True)
class LabelSpec:
    artwork: Path
    width_mm: float
    height_mm: float
    trim_mm: float = 0.0
    bleed_mm: float = 0.0
    safe_area_mm: float = 0.0
    min_dpi: int = 300
    required_copy: tuple[str, ...] = ()
    barcode_value: str | None = None
    qr_value: str | None = None
    native_evidence: NativeEvidenceSpec | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any], root: Path) -> LabelSpec:
        required = ("artwork", "width_mm", "height_mm")
        absent = [key for key in required if key not in data]
        if absent:
            raise ValueError(f"Missing required configuration fields: {', '.join(absent)}")
        artwork = (root / str(data["artwork"])).resolve()
        width, height = float(data["width_mm"]), float(data["height_mm"])
        if width <= 0 or height <= 0:
            raise ValueError("width_mm and height_mm must be positive")
        values = {
            key: float(data.get(key, 0))
            for key in ("trim_mm", "bleed_mm", "safe_area_mm")
        }
        if any(value < 0 for value in values.values()):
            raise ValueError("trim_mm, bleed_mm, and safe_area_mm cannot be negative")
        if values["safe_area_mm"] * 2 >= min(width, height):
            raise ValueError("safe_area_mm leaves no printable area")
        min_dpi = int(data.get("min_dpi", 300))
        if min_dpi <= 0:
            raise ValueError("min_dpi must be positive")
        native_evidence = (
            NativeEvidenceSpec.from_dict(data["native_evidence"], root)
            if "native_evidence" in data
            else None
        )
        return cls(
            artwork=artwork,
            width_mm=width,
            height_mm=height,
            min_dpi=min_dpi,
            required_copy=tuple(str(value) for value in data.get("required_copy", [])),
            barcode_value=_optional_string(data.get("barcode_value")),
            qr_value=_optional_string(data.get("qr_value")),
            native_evidence=native_evidence,
            **values,
        )


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    value = str(value)
    if not value:
        raise ValueError("Barcode and QR expected values cannot be empty")
    return value
