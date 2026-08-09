"""Specification models and strict JSON loading."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class SymbolExpectation:
    """A machine-readable symbol expected somewhere in the supplied artwork."""

    value: str
    format: str | None = None

    @classmethod
    def from_mapping(cls, value: dict[str, object]) -> SymbolExpectation:
        text = value.get("value")
        symbol_format = value.get("format")
        if not isinstance(text, str) or not text:
            raise ValueError("symbol 'value' must be a non-empty string")
        if symbol_format is not None and not isinstance(symbol_format, str):
            raise ValueError("symbol 'format' must be a string")
        return cls(value=text, format=symbol_format)


@dataclass(frozen=True)
class LabelSpec:
    """The subset of a label specification that can be objectively verified."""

    width_mm: float
    height_mm: float
    trim_mm: float = 0.0
    bleed_mm: float = 0.0
    safe_area_mm: float = 0.0
    minimum_dpi: int = 300
    required_copy: tuple[str, ...] = ()
    barcode: SymbolExpectation | None = None
    qr: SymbolExpectation | None = None
    tolerance_mm: float = 0.25
    color_mode: str | None = None

    def __post_init__(self) -> None:
        if self.width_mm <= 0 or self.height_mm <= 0:
            raise ValueError("width_mm and height_mm must be positive")
        if min(self.trim_mm, self.bleed_mm, self.safe_area_mm) < 0:
            raise ValueError("trim_mm, bleed_mm, and safe_area_mm cannot be negative")
        if self.minimum_dpi <= 0:
            raise ValueError("minimum_dpi must be positive")
        if self.tolerance_mm < 0:
            raise ValueError("tolerance_mm cannot be negative")

    @property
    def finished_width_mm(self) -> float:
        return self.width_mm + 2 * self.bleed_mm

    @property
    def finished_height_mm(self) -> float:
        return self.height_mm + 2 * self.bleed_mm

    @classmethod
    def from_mapping(cls, value: dict[str, object]) -> LabelSpec:
        allowed = {
            "width_mm",
            "height_mm",
            "trim_mm",
            "bleed_mm",
            "safe_area_mm",
            "minimum_dpi",
            "required_copy",
            "barcode",
            "qr",
            "tolerance_mm",
            "color_mode",
        }
        unknown = set(value) - allowed
        if unknown:
            raise ValueError(f"unknown specification fields: {', '.join(sorted(unknown))}")
        copy = value.get("required_copy", [])
        if not isinstance(copy, list) or not all(isinstance(item, str) and item for item in copy):
            raise ValueError("required_copy must be an array of non-empty strings")
        kwargs = dict(value)
        for name in ("barcode", "qr"):
            if kwargs.get(name) is not None:
                if not isinstance(kwargs[name], dict):
                    raise ValueError(f"{name} must be an object")
                kwargs[name] = SymbolExpectation.from_mapping(kwargs[name])  # type: ignore[arg-type]
        kwargs["required_copy"] = tuple(copy)
        try:
            return cls(**kwargs)  # type: ignore[arg-type]
        except TypeError as exc:
            raise ValueError(f"invalid label specification: {exc}") from exc

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def load_spec(path: str | Path) -> LabelSpec:
    """Load a label specification from a JSON file."""

    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON specification: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError("label specification root must be an object")
    return LabelSpec.from_mapping(raw)
