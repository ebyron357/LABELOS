"""Artwork and PDF validation with evidence suitable for operator reports."""

from __future__ import annotations

import io
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

import pymupdf as fitz
import zxingcpp
from PIL import Image

from .models import LabelSpec, SymbolExpectation

MM_PER_INCH = 25.4


@dataclass
class Check:
    name: str
    passed: bool
    detail: str
    severity: str = "error"


@dataclass
class ValidationResult:
    source: str
    checks: list[Check] = field(default_factory=list)
    metadata: dict[str, object] = field(default_factory=dict)

    @property
    def valid(self) -> bool:
        return all(check.passed or check.severity != "error" for check in self.checks)

    def add(self, name: str, passed: bool, detail: str, severity: str = "error") -> None:
        self.checks.append(Check(name, passed, detail, severity))

    def to_dict(self) -> dict[str, object]:
        return {
            "source": self.source,
            "valid": self.valid,
            "checks": [asdict(c) for c in self.checks],
            "metadata": self.metadata,
        }


def _dimension_check(
    result: ValidationResult, width_mm: float, height_mm: float, spec: LabelSpec
) -> None:
    expected = (spec.finished_width_mm, spec.finished_height_mm)
    actual = (width_mm, height_mm)
    direct = all(abs(a - e) <= spec.tolerance_mm for a, e in zip(actual, expected, strict=True))
    rotated = all(
        abs(a - e) <= spec.tolerance_mm for a, e in zip(actual, reversed(expected), strict=True)
    )
    detail = (
        f"actual {width_mm:.2f} × {height_mm:.2f} mm; expected "
        f"{expected[0]:.2f} × {expected[1]:.2f} mm ± {spec.tolerance_mm:.2f} mm"
    )
    result.add(
        "dimensions",
        direct or rotated,
        detail,
    )


def _expect_symbol(
    result: ValidationResult, kind: str, expected: SymbolExpectation | None, symbols: list[object]
) -> None:
    if expected is None:
        return

    def normalized_format(value: object) -> str:
        return re.sub(r"[^A-Z0-9]", "", str(value).upper())

    matches = [
        symbol
        for symbol in symbols
        if getattr(symbol, "text", None) == expected.value
        and (
            expected.format is None
            or normalized_format(getattr(symbol, "format", ""))
            == normalized_format(expected.format)
        )
    ]
    found = (
        ", ".join(f"{getattr(s, 'format', '?')}:{getattr(s, 'text', '?')}" for s in symbols)
        or "none"
    )
    result.add(
        kind,
        bool(matches),
        f"expected {expected.format or 'any'}:{expected.value}; decoded {found}",
    )


def _copy_check(result: ValidationResult, required_copy: tuple[str, ...], text: str) -> None:
    normalized = " ".join(text.casefold().split())
    for copy in required_copy:
        found = " ".join(copy.casefold().split()) in normalized
        result.add("required_copy", found, f"{'found' if found else 'missing'}: {copy!r}")


def validate_image(path: str | Path, spec: LabelSpec) -> ValidationResult:
    """Validate a raster artwork file and decode all available symbols."""

    source = Path(path)
    result = ValidationResult(str(source))
    with Image.open(source) as image:
        dpi = image.info.get("dpi", (0, 0))
        x_dpi = float(dpi[0] or 0)
        y_dpi = float(dpi[1] or 0)
        width_mm = image.width / x_dpi * MM_PER_INCH if x_dpi else 0
        height_mm = image.height / y_dpi * MM_PER_INCH if y_dpi else 0
        result.metadata.update(
            {
                "pixels": [image.width, image.height],
                "dpi": [round(x_dpi, 2), round(y_dpi, 2)],
                "mode": image.mode,
            }
        )
        # PNG stores pixels-per-meter as an integer, so a nominal 300-DPI image may
        # round-trip as 299.9994. Treat sub-DPI metadata quantization as equivalent.
        resolution_ok = x_dpi + 0.01 >= spec.minimum_dpi and y_dpi + 0.01 >= spec.minimum_dpi
        result.add(
            "resolution",
            resolution_ok,
            f"{x_dpi:.1f} × {y_dpi:.1f} DPI; minimum {spec.minimum_dpi}",
        )
        _dimension_check(result, width_mm, height_mm, spec)
        if spec.color_mode:
            result.add(
                "color_mode",
                image.mode.upper() == spec.color_mode.upper(),
                f"actual {image.mode}; expected {spec.color_mode}",
            )
        symbols = zxingcpp.read_barcodes(image.convert("RGB"))
        _expect_symbol(result, "barcode", spec.barcode, symbols)
        _expect_symbol(result, "qr", spec.qr, symbols)
        _copy_check(
            result, spec.required_copy, " ".join(getattr(symbol, "text", "") for symbol in symbols)
        )
    return result


def validate_pdf(path: str | Path, spec: LabelSpec) -> ValidationResult:
    """Validate PDF geometry, extractable copy, and decodable rasterized symbols."""

    source = Path(path)
    result = ValidationResult(str(source))
    document = fitz.open(source)
    try:
        result.add(
            "page_count", len(document) == 1, f"{len(document)} page(s); exactly one required"
        )
        if not document:
            return result
        page = document[0]
        width_mm = page.rect.width / 72 * MM_PER_INCH
        height_mm = page.rect.height / 72 * MM_PER_INCH
        result.metadata["page_size_mm"] = [round(width_mm, 2), round(height_mm, 2)]
        _dimension_check(result, width_mm, height_mm, spec)
        _copy_check(result, spec.required_copy, page.get_text("text"))
        pixmap = page.get_pixmap(dpi=max(spec.minimum_dpi, 300), alpha=False)
        raster = Image.open(io.BytesIO(pixmap.tobytes("png"))).convert("RGB")
        symbols = zxingcpp.read_barcodes(raster)
        _expect_symbol(result, "barcode", spec.barcode, symbols)
        _expect_symbol(result, "qr", spec.qr, symbols)
        result.add("pdf_readable", True, "PDF parsed and rendered successfully")
    finally:
        document.close()
    return result
