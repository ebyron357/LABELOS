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


ARTIFACT_KEYS = ("evidence_json", "log", "preview_png", "native_artwork")
REQUIRED_ARTIFACT_KEYS = ("evidence_json", "log")
EVIDENCE_KEYS = ARTIFACT_KEYS + ("required_layers", "required_objects")


@dataclass(frozen=True)
class NativeEvidenceSpec:
    """Operator-supplied proof that a native build produced the artwork.

    Paths are kept as declared and resolved at check time so unsafe or absent
    artifacts become reported errors rather than import-time exceptions.
    """

    root: Path
    evidence_json: str | None = None
    log: str | None = None
    preview_png: str | None = None
    native_artwork: str | None = None
    required_layers: tuple[str, ...] = ()
    required_objects: tuple[str, ...] = ()

    def declared(self) -> dict[str, str]:
        """Return the artifact keys that the configuration actually points at."""
        return {
            key: value
            for key in ARTIFACT_KEYS
            if (value := getattr(self, key)) is not None
        }

    @classmethod
    def from_dict(cls, data: Any, root: Path) -> NativeEvidenceSpec:
        if not isinstance(data, dict):
            raise TypeError("native_evidence must be a JSON object")
        unknown = sorted(set(data) - set(EVIDENCE_KEYS))
        if unknown:
            raise ValueError(f"Unknown native_evidence fields: {', '.join(unknown)}")
        paths: dict[str, str] = {}
        for key in ARTIFACT_KEYS:
            if key not in data:
                continue
            value = data[key]
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"native_evidence.{key} must be a non-empty string path")
            paths[key] = value
        return cls(
            root=root,
            required_layers=_names(data, "required_layers"),
            required_objects=_names(data, "required_objects"),
            **paths,
        )


def _names(data: dict[str, Any], key: str) -> tuple[str, ...]:
    values = data.get(key, [])
    if not isinstance(values, list):
        raise TypeError(f"native_evidence.{key} must be a list of names")
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"native_evidence.{key} entries must be non-empty strings")
    return tuple(values)


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
            NativeEvidenceSpec.from_dict(data["native_evidence"], Path(root).resolve())
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
