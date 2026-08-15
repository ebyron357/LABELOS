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
        return cls(
            artwork=artwork,
            width_mm=width,
            height_mm=height,
            min_dpi=min_dpi,
            required_copy=tuple(str(value) for value in data.get("required_copy", [])),
            barcode_value=_optional_string(data.get("barcode_value")),
            qr_value=_optional_string(data.get("qr_value")),
            **values,
        )

    def to_dict(self, artwork: str | None = None) -> dict[str, Any]:
        """Serialize a self-contained label specification for a release package."""
        return {
            "artwork": artwork or str(self.artwork),
            "width_mm": self.width_mm,
            "height_mm": self.height_mm,
            "trim_mm": self.trim_mm,
            "bleed_mm": self.bleed_mm,
            "safe_area_mm": self.safe_area_mm,
            "min_dpi": self.min_dpi,
            "required_copy": list(self.required_copy),
            "barcode_value": self.barcode_value,
            "qr_value": self.qr_value,
        }


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    value = str(value)
    if not value:
        raise ValueError("Barcode and QR expected values cannot be empty")
    return value
