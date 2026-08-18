"""Artwork validators. Optional readers are reported, never silently skipped."""

from __future__ import annotations

import re
import struct
import xml.etree.ElementTree as ET
from collections.abc import Callable
from io import BytesIO
from pathlib import Path

from .models import LabelSpec, Report

MM_PER_POINT = 25.4 / 72


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
    _validate_codes(spec, report)
    _validate_safe_area(spec, report)
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
    document = pymupdf.open(spec.artwork)
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


def _validate_safe_area(spec: LabelSpec, report: Report) -> None:
    """Ensure detectable artwork stays inside the configured safe area.

    The physical artwork includes bleed, so the safe area begins after both the
    bleed and the configured inset.  A raster image has no separable content
    objects; it therefore cannot prove a safe area and fails closed when one is
    requested.
    """

    if not spec.safe_area_mm:
        return
    report.checks.append("safe-area")
    outer_width = spec.width_mm + 2 * spec.bleed_mm
    outer_height = spec.height_mm + 2 * spec.bleed_mm
    inset = spec.bleed_mm + spec.safe_area_mm
    bounds = (inset, inset, outer_width - inset, outer_height - inset)
    report.metadata["safe_area_mm"] = {
        "left": round(bounds[0], 3),
        "top": round(bounds[1], 3),
        "right": round(bounds[2], 3),
        "bottom": round(bounds[3], 3),
    }
    suffix = spec.artwork.suffix.lower()
    if suffix == ".png":
        report.add(
            "SAFE_AREA_UNVERIFIABLE",
            "error",
            "Cannot distinguish critical content from the background of a raster PNG",
        )
        return
    if suffix == ".svg":
        _validate_svg_safe_area(spec.artwork, outer_width, outer_height, bounds, report)
    elif suffix == ".pdf":
        _validate_pdf_safe_area(spec.artwork, outer_width, outer_height, bounds, report)


def _validate_svg_safe_area(
    artwork: Path, outer_width: float, outer_height: float, safe: tuple[float, float, float, float], report: Report
) -> None:
    text = artwork.read_text(encoding="utf-8", errors="replace")
    if re.search(r"<!DOCTYPE|<!ENTITY", text, re.IGNORECASE):
        report.add("SVG_UNSAFE_XML", "error", "SVG contains a DOCTYPE or entity declaration")
        return
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return  # SVG syntax has already been reported by the format validator.
    for element in root.iter():
        tag = element.tag.rsplit("}", 1)[-1].lower()
        if tag in {"svg", "defs", "title", "desc", "metadata", "style"}:
            continue
        if element.get("transform"):
            report.add(
                "SAFE_AREA_UNVERIFIABLE",
                "error",
                f"Cannot validate transformed SVG {tag} element against the safe area",
            )
            continue
        box = _svg_element_box(element, tag)
        if box is None:
            report.add(
                "SAFE_AREA_UNVERIFIABLE",
                "error",
                f"Cannot determine bounds for SVG {tag} element",
            )
            continue
        if _is_full_canvas_background(box, outer_width, outer_height):
            continue
        _check_safe_bounds(box, safe, report, f"SVG {tag}")


def _svg_element_box(element: ET.Element, tag: str) -> tuple[float, float, float, float] | None:
    def number(name: str, default: float | None = None) -> float | None:
        value = element.get(name)
        if value is None:
            return default
        match = re.fullmatch(r"\s*([+-]?[0-9.]+)\s*", value)
        return float(match.group(1)) if match else None

    if tag in {"rect", "image", "foreignobject"}:
        x, y = number("x", 0), number("y", 0)
        width, height = number("width"), number("height")
        if None in {x, y, width, height}:
            return None
        return x, y, x + width, y + height
    if tag == "circle":
        cx, cy, radius = number("cx", 0), number("cy", 0), number("r")
        if None in {cx, cy, radius}:
            return None
        return cx - radius, cy - radius, cx + radius, cy + radius
    if tag == "ellipse":
        cx, cy, rx, ry = number("cx", 0), number("cy", 0), number("rx"), number("ry")
        if None in {cx, cy, rx, ry}:
            return None
        return cx - rx, cy - ry, cx + rx, cy + ry
    if tag in {"line", "polyline", "polygon", "path", "use", "text", "tspan"}:
        # Font and path geometry need a renderer to calculate reliably. A text
        # insertion point is still a useful fail-closed lower bound.
        if tag in {"text", "tspan"}:
            x, y = number("x"), number("y")
            return (x, y, x, y) if x is not None and y is not None else None
        return None
    return None


def _validate_pdf_safe_area(
    artwork: Path, outer_width: float, outer_height: float, safe: tuple[float, float, float, float], report: Report
) -> None:
    try:
        import pymupdf
    except ImportError:
        # _validate_pdf has already issued the actionable reader error.
        return

    document = pymupdf.open(artwork)
    try:
        if document.page_count != 1:
            return
        page = document[0]
        page_bounds = (page.rect.width * MM_PER_POINT, page.rect.height * MM_PER_POINT)
        for block in page.get_text("blocks"):
            _check_safe_bounds(_rect_mm(block[:4]), safe, report, "PDF text")
        for image in page.get_images(full=True):
            for rect in page.get_image_rects(image[0]):
                _check_safe_bounds(_rect_mm(rect), safe, report, "PDF image")
        for drawing in page.get_drawings():
            box = _rect_mm(drawing["rect"])
            if not _is_full_canvas_background(box, *page_bounds):
                _check_safe_bounds(box, safe, report, "PDF vector")
    finally:
        document.close()


def _rect_mm(rect) -> tuple[float, float, float, float]:
    return tuple(float(value) * MM_PER_POINT for value in rect)


def _is_full_canvas_background(box: tuple[float, float, float, float], width: float, height: float) -> bool:
    return box[0] <= 0.1 and box[1] <= 0.1 and box[2] >= width - 0.1 and box[3] >= height - 0.1


def _check_safe_bounds(
    box: tuple[float, float, float, float],
    safe: tuple[float, float, float, float],
    report: Report,
    object_name: str,
) -> None:
    if box[0] < safe[0] - 0.1 or box[1] < safe[1] - 0.1 or box[2] > safe[2] + 0.1 or box[3] > safe[3] + 0.1:
        report.add(
            "SAFE_AREA_VIOLATION",
            "error",
            f"{object_name} bounds {box[0]:.2f},{box[1]:.2f}–{box[2]:.2f},{box[3]:.2f} mm exceed safe area",
        )


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
