"""Artwork validators. Optional readers are reported, never silently skipped."""

from __future__ import annotations

import re
import struct
from collections.abc import Callable
from io import BytesIO
from math import ceil, floor
from pathlib import Path
from typing import Any

from .models import LabelSpec, Report

MM_PER_POINT = 25.4 / 72
SAFE_AREA_BACKGROUND_TOLERANCE = 8


def validate(spec: LabelSpec) -> Report:
    report = Report(source=str(spec.artwork))
    if not spec.artwork.is_file():
        report.add("ARTWORK_MISSING", "error", "Artwork file does not exist", str(spec.artwork))
        return report

    suffix = spec.artwork.suffix.lower()
    validators: dict[str, Callable[[LabelSpec, Report], str]] = {
        ".png": _validate_png,
        ".svg": _validate_svg,
        ".pdf": _validate_pdf,
    }
    validator = validators.get(suffix)
    if validator is None:
        report.add("FORMAT_UNSUPPORTED", "error", f"Unsupported artwork format: {suffix}")
        return report
    text = validator(spec, report)
    _validate_required_copy(spec, text, report)
    _validate_safe_area(spec, report)
    _validate_codes(spec, report)
    report.metadata["spec"] = {
        "width_mm": spec.width_mm,
        "height_mm": spec.height_mm,
        "bleed_mm": spec.bleed_mm,
        "trim_mm": spec.trim_mm,
        "safe_area_mm": spec.safe_area_mm,
        "min_dpi": spec.min_dpi,
    }
    return report


def _validate_png(spec: LabelSpec, report: Report) -> str:
    data = spec.artwork.read_bytes()
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n":
        report.add("PNG_INVALID", "error", "File is not a valid PNG")
        return ""
    width, height = struct.unpack(">II", data[16:24])
    dpi = _png_dpi(data)
    report.checks.extend(["format:png", "dimensions", "raster-resolution"])
    report.metadata["pixels"] = {"width": width, "height": height}
    _validate_pixel_dimensions(spec, width, height, dpi, report)
    return ""


def _png_dpi(data: bytes) -> float | None:
    index = 8
    while index + 12 <= len(data):
        length = struct.unpack(">I", data[index : index + 4])[0]
        kind = data[index + 4 : index + 8]
        chunk = data[index + 8 : index + 8 + length]
        if kind == b"pHYs" and len(chunk) == 9 and chunk[8] == 1:
            return struct.unpack(">I", chunk[:4])[0] * 0.0254
        index += 12 + length
    return None


def _validate_pixel_dimensions(
    spec: LabelSpec, width_px: int, height_px: int, dpi: float | None, report: Report
) -> None:
    expected = (
        (spec.width_mm + 2 * spec.bleed_mm) / 25.4,
        (spec.height_mm + 2 * spec.bleed_mm) / 25.4,
    )
    if dpi is None:
        dpi = min(width_px / expected[0], height_px / expected[1])
        report.add("DPI_METADATA_MISSING", "warning", "PNG has no pHYs DPI metadata; inferred DPI used")
    actual = (width_px / expected[0], height_px / expected[1])
    report.metadata["dpi"] = round(min(actual), 2)
    if min(actual) < spec.min_dpi:
        report.add(
            "DPI_TOO_LOW",
            "error",
            f"Effective resolution {min(actual):.1f} DPI is below {spec.min_dpi} DPI",
        )


def _validate_svg(spec: LabelSpec, report: Report) -> str:
    text = spec.artwork.read_text(encoding="utf-8", errors="replace")
    match = re.search(r"<svg\b[^>]*>", text, re.IGNORECASE)
    if not match:
        report.add("SVG_INVALID", "error", "No SVG root element found")
        return text
    root = match.group(0)
    width, height = (_svg_mm(root, "width"), _svg_mm(root, "height"))
    report.checks.extend(["format:svg", "dimensions"])
    if width is None or height is None:
        report.add("SVG_DIMENSIONS_MISSING", "error", "SVG width and height must use physical units")
    else:
        _validate_physical_size(spec, width, height, report)
    return text


def _svg_mm(root: str, attr: str) -> float | None:
    match = re.search(fr'\b{attr}=["\']\s*([0-9.]+)\s*(mm|cm|in|pt)["\']', root, re.IGNORECASE)
    if not match:
        return None
    value, unit = float(match.group(1)), match.group(2).lower()
    return value * {"mm": 1, "cm": 10, "in": 25.4, "pt": MM_PER_POINT}[unit]


def _validate_pdf(spec: LabelSpec, report: Report) -> str:
    try:
        import pymupdf
    except ImportError:
        report.add("PDF_READER_UNAVAILABLE", "error", "Install PyMuPDF to inspect PDF artwork")
        return ""
    try:
        document = pymupdf.open(spec.artwork)
    except (OSError, RuntimeError) as error:
        report.add("PDF_INVALID", "error", f"Could not open PDF artwork: {error}")
        return ""
    try:
        if document.page_count != 1:
            report.add("PDF_PAGE_COUNT", "error", f"Artwork must contain one page, found {document.page_count}")
            return ""
        page = document[0]
        _validate_physical_size(spec, page.rect.width * MM_PER_POINT, page.rect.height * MM_PER_POINT, report)
        text = page.get_text()
        report.checks.extend(["format:pdf", "dimensions", "pdf-readable"])
        report.metadata["pdf"] = {"pages": document.page_count, "fonts": len(page.get_fonts())}
        if not page.get_fonts():
            report.add("PDF_NO_FONTS", "warning", "PDF contains no embedded font resources")
        return text
    finally:
        document.close()


def _validate_physical_size(spec: LabelSpec, width: float, height: float, report: Report) -> None:
    report.metadata["artwork_size_mm"] = {"width": round(width, 3), "height": round(height, 3)}
    expected = (spec.width_mm + 2 * spec.bleed_mm, spec.height_mm + 2 * spec.bleed_mm)
    if abs(width - expected[0]) > 0.1 or abs(height - expected[1]) > 0.1:
        report.add(
            "DIMENSIONS_MISMATCH",
            "error",
            f"Artwork is {width:.2f}×{height:.2f} mm; expected {expected[0]:.2f}×{expected[1]:.2f} mm",
        )


def _validate_required_copy(spec: LabelSpec, text: str, report: Report) -> None:
    if spec.required_copy:
        report.checks.append("required-copy")
    for value in spec.required_copy:
        if value not in text:
            report.add("REQUIRED_COPY_MISSING", "error", f"Required copy not found: {value!r}")


def _validate_safe_area(spec: LabelSpec, report: Report) -> None:
    """Reject non-background artwork in the configured bleed-plus-safe-area boundary."""

    if spec.safe_area_mm <= 0:
        return
    report.checks.append("safe-area")
    try:
        from PIL import Image
    except ImportError:
        report.add("SAFE_AREA_UNCHECKABLE", "error", "Install Pillow to inspect the artwork safe area")
        return
    try:
        with _safe_area_image(spec.artwork, Image) as image:
            _inspect_safe_area(spec, image, report, require_opaque=spec.artwork.suffix.lower() == ".png")
    except (OSError, RuntimeError, ValueError) as error:
        report.add("SAFE_AREA_UNCHECKABLE", "error", f"Could not inspect artwork safe area: {error}")


def _safe_area_image(artwork: Path, image_module: Any):
    """Return an RGBA image for safe-area inspection at a print-appropriate resolution."""

    if artwork.suffix.lower() == ".png":
        image = image_module.open(artwork)
        image.load()
        return image.convert("RGBA")
    import pymupdf

    document = pymupdf.open(artwork)
    try:
        if document.page_count != 1:
            raise ValueError("artwork must contain exactly one page")
        pixmap = document[0].get_pixmap(dpi=300, alpha=True)
        image = image_module.open(BytesIO(pixmap.tobytes("png")))
        image.load()
        return image.convert("RGBA")
    finally:
        document.close()


def _inspect_safe_area(spec: LabelSpec, image: Any, report: Report, require_opaque: bool) -> None:
    width, height = image.size
    if width < 3 or height < 3:
        raise ValueError("artwork is too small to inspect")
    pixels = image.load()
    corners = [pixels[0, 0], pixels[width - 1, 0], pixels[0, height - 1], pixels[width - 1, height - 1]]
    if require_opaque and any(pixel[3] != 255 for pixel in corners):
        raise ValueError("transparent edge background cannot be validated")
    background = corners[0][:3]
    if any(_color_distance(pixel[:3], background) > SAFE_AREA_BACKGROUND_TOLERANCE for pixel in corners[1:]):
        raise ValueError("edge background is not uniform")

    full_width_mm = spec.width_mm + 2 * spec.bleed_mm
    full_height_mm = spec.height_mm + 2 * spec.bleed_mm
    margin_mm = spec.bleed_mm + spec.safe_area_mm
    left = floor(margin_mm / full_width_mm * width)
    top = floor(margin_mm / full_height_mm * height)
    right = ceil(width - margin_mm / full_width_mm * width)
    bottom = ceil(height - margin_mm / full_height_mm * height)
    if left >= right or top >= bottom:
        raise ValueError("safe area leaves no inspectable artwork region")

    protected_pixels = 0
    for y in range(height):
        for x in range(width):
            if left <= x < right and top <= y < bottom:
                continue
            pixel = pixels[x, y]
            if (
                (require_opaque and pixel[3] != 255)
                or _color_distance(pixel[:3], background) > SAFE_AREA_BACKGROUND_TOLERANCE
            ):
                protected_pixels += 1
    report.metadata["safe_area"] = {
        "margin_mm": margin_mm,
        "background_rgb": list(background),
        "protected_pixels": protected_pixels,
    }
    if protected_pixels:
        report.add(
            "SAFE_AREA_VIOLATION",
            "error",
            f"Found {protected_pixels} non-background pixels outside the {spec.safe_area_mm:g} mm safe area",
        )


def _color_distance(left: tuple[int, int, int], right: tuple[int, int, int]) -> int:
    return max(abs(component - baseline) for component, baseline in zip(left, right))


def _validate_codes(spec: LabelSpec, report: Report) -> None:
    expectations = (("barcode", spec.barcode_value), ("qr", spec.qr_value))
    if not any(value for _, value in expectations):
        return
    report.checks.append("code-decode")
    try:
        import zxingcpp
        from PIL import Image
    except ImportError:
        report.add(
            "DECODER_UNAVAILABLE",
            "error",
            "Install Pillow and zxing-cpp to validate barcode or QR values",
        )
        return
    try:
        with _code_image(spec.artwork, Image) as image:
            results = zxingcpp.read_barcodes(image)
    except (ImportError, IndexError, OSError, RuntimeError, ValueError) as error:
        report.add("CODE_DECODE_FAILED", "error", f"Could not decode artwork: {error}")
        return
    decoded = {result.text for result in results}
    report.metadata["decoded_values"] = sorted(decoded)
    for kind, expected in expectations:
        if expected and expected not in decoded:
            report.add("CODE_VALUE_MISMATCH", "error", f"Expected {kind} value not decoded: {expected!r}")


def _code_image(artwork: Path, image_module):
    """Return artwork as a Pillow image, rasterizing vector sources for ZXing."""

    if artwork.suffix.lower() == ".png":
        return image_module.open(artwork)
    import pymupdf

    document = pymupdf.open(artwork)
    try:
        if document.page_count < 1:
            raise ValueError("Artwork contains no pages to decode")
        page = document[0]
        pixmap = page.get_pixmap(dpi=300, alpha=False)
        image = image_module.open(BytesIO(pixmap.tobytes("png")))
        image.load()
        return image
    finally:
        document.close()
