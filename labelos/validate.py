"""Artwork validators. Optional readers are reported, never silently skipped."""

from __future__ import annotations

import re
import struct
from collections.abc import Callable
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree

from .models import LabelSpec, Report

MM_PER_POINT = 25.4 / 72
SAFE_AREA_RENDER_DPI = 300
SAFE_AREA_RENDER_TOLERANCE_MM = 25.4 / SAFE_AREA_RENDER_DPI


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
    report.metadata["spec"] = spec.to_dict(artwork=spec.artwork.name)
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
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError as error:
        report.add("SVG_INVALID", "error", f"Invalid SVG XML: {error}")
        return text
    if root.tag.rsplit("}", 1)[-1].lower() != "svg":
        report.add("SVG_INVALID", "error", "No SVG root element found")
        return text
    width, height = (_svg_mm(root.get("width")), _svg_mm(root.get("height")))
    report.checks.extend(["format:svg", "dimensions"])
    if width is None or height is None:
        report.add("SVG_DIMENSIONS_MISSING", "error", "SVG width and height must use physical units")
    else:
        _validate_physical_size(spec, width, height, report)
    return text


def _svg_mm(value: str | None) -> float | None:
    match = re.fullmatch(r"\s*([0-9.]+)\s*(mm|cm|in|pt)\s*", value or "", re.IGNORECASE)
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
    except (OSError, RuntimeError, ValueError) as error:
        report.add("PDF_INVALID", "error", f"Could not read PDF artwork: {error}")
        return ""
    try:
        if document.page_count != 1:
            report.add("PDF_PAGE_COUNT", "error", f"Artwork must contain one page, found {document.page_count}")
            return ""
        page = document[0]
        _validate_physical_size(spec, page.rect.width * MM_PER_POINT, page.rect.height * MM_PER_POINT, report)
        text = page.get_text()
        report.checks.extend(["format:pdf", "dimensions", "pdf-readable"])
        report.metadata["pdf"] = {
            "pages": document.page_count,
            "fonts": len(page.get_fonts()),
            "rotation": page.rotation,
        }
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
    """Reject visible marks which intrude into the configured trim-safe bounds."""
    if not spec.safe_area_mm:
        return
    report.checks.append("safe-area")
    if any(issue.code in {"SVG_INVALID", "PDF_INVALID", "PDF_PAGE_COUNT"} for issue in report.issues):
        return
    try:
        bounds = _visible_bounds_mm(spec)
    except ImportError:
        report.add(
            "SAFE_AREA_UNCHECKABLE",
            "error",
            "Install Pillow and PyMuPDF to inspect artwork safe areas",
        )
        return
    except (OSError, RuntimeError, ValueError) as error:
        report.add("SAFE_AREA_UNCHECKABLE", "error", f"Could not inspect safe area: {error}")
        return
    report.metadata["safe_area"] = {
        "visible_bounds_mm": [round(value, 3) for value in bounds] if bounds else None,
        "allowed_bounds_mm": [round(value, 3) for value in _safe_bounds(spec)],
    }
    if bounds and _outside_safe_area(bounds, spec):
        report.add(
            "SAFE_AREA_VIOLATION",
            "error",
            "Visible non-background artwork extends outside the configured bleed and safe area",
        )


def _safe_bounds(spec: LabelSpec) -> tuple[float, float, float, float]:
    inset = spec.bleed_mm + spec.safe_area_mm
    return (
        inset,
        inset,
        spec.width_mm + 2 * spec.bleed_mm - inset,
        spec.height_mm + 2 * spec.bleed_mm - inset,
    )


def _outside_safe_area(bounds: tuple[float, float, float, float], spec: LabelSpec) -> bool:
    left, top, right, bottom = _safe_bounds(spec)
    x0, y0, x1, y1 = bounds
    return (
        x0 < left - SAFE_AREA_RENDER_TOLERANCE_MM
        or y0 < top - SAFE_AREA_RENDER_TOLERANCE_MM
        or x1 > right + SAFE_AREA_RENDER_TOLERANCE_MM
        or y1 > bottom + SAFE_AREA_RENDER_TOLERANCE_MM
    )


def _visible_bounds_mm(spec: LabelSpec) -> tuple[float, float, float, float] | None:
    """Render vectors at production resolution and locate non-background pixels."""
    from PIL import Image

    artwork = spec.artwork
    if artwork.suffix.lower() == ".png":
        with Image.open(artwork) as image:
            return _occupied_bounds_mm(
                image.convert("RGBA"),
                spec.width_mm + 2 * spec.bleed_mm,
                spec.height_mm + 2 * spec.bleed_mm,
            )

    import pymupdf

    document = pymupdf.open(artwork)
    try:
        if document.page_count != 1:
            raise ValueError(f"Expected one rendered page, found {document.page_count}")
        page = document[0]
        pixmap = page.get_pixmap(dpi=SAFE_AREA_RENDER_DPI, alpha=True)
        image = Image.open(BytesIO(pixmap.tobytes("png"))).convert("RGBA")
        return _occupied_bounds_mm(
            image, page.rect.width * MM_PER_POINT, page.rect.height * MM_PER_POINT
        )
    finally:
        document.close()


def _occupied_bounds_mm(image, width_mm: float, height_mm: float) -> tuple[float, float, float, float] | None:
    from PIL import Image, ImageChops

    white = Image.new("RGBA", image.size, "white")
    rendered = Image.alpha_composite(white, image).convert("RGB")
    corners = (
        rendered.getpixel((0, 0)),
        rendered.getpixel((rendered.width - 1, 0)),
        rendered.getpixel((0, rendered.height - 1)),
        rendered.getpixel((rendered.width - 1, rendered.height - 1)),
    )
    background = Image.new("RGB", image.size, corners[0] if len(set(corners)) == 1 else (255, 255, 255))
    occupied = ImageChops.difference(rendered, background).getbbox()
    if occupied is None:
        return None
    left, top, right, bottom = occupied
    return (
        left * width_mm / image.width,
        top * height_mm / image.height,
        right * width_mm / image.width,
        bottom * height_mm / image.height,
    )


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
