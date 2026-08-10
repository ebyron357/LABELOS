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
MM_PER_SVG_PIXEL = 25.4 / 96


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
    _validate_png_safe_area(spec, report)
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
        _validate_svg_safe_area(spec, text, width, height, report)
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
        _validate_pdf_safe_area(spec, page, report)
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


def _safe_area_bounds(spec: LabelSpec) -> tuple[float, float, float, float]:
    """Return the safe rectangle in bleed-inclusive artwork millimetres."""
    inset = spec.bleed_mm + spec.safe_area_mm
    return (inset, inset, spec.width_mm + 2 * spec.bleed_mm - inset, spec.height_mm + 2 * spec.bleed_mm - inset)


def _validate_safe_area_box(
    spec: LabelSpec, report: Report, label: str, box: tuple[float, float, float, float]
) -> None:
    left, top, right, bottom = _safe_area_bounds(spec)
    x0, y0, x1, y1 = box
    if x0 < left or y0 < top or x1 > right or y1 > bottom:
        report.add(
            "SAFE_AREA_VIOLATION",
            "error",
            (
                f"{label} at {x0:.2f},{y0:.2f}–{x1:.2f},{y1:.2f} mm exceeds "
                f"safe area {left:.2f},{top:.2f}–{right:.2f},{bottom:.2f} mm"
            ),
        )


def _validate_png_safe_area(spec: LabelSpec, report: Report) -> None:
    if spec.safe_area_mm == 0:
        return
    report.checks.append("safe-area")
    try:
        from PIL import Image
    except ImportError:
        report.add("SAFE_AREA_UNAVAILABLE", "error", "Install Pillow to inspect raster safe areas")
        return
    with Image.open(spec.artwork) as image:
        image = image.convert("RGBA")
        pixels = image.load()
        min_x, min_y, max_x, max_y = image.width, image.height, -1, -1
        for y in range(image.height):
            for x in range(image.width):
                red, green, blue, alpha = pixels[x, y]
                if alpha and (red < 250 or green < 250 or blue < 250):
                    min_x, min_y = min(min_x, x), min(min_y, y)
                    max_x, max_y = max(max_x, x), max(max_y, y)
    if max_x == -1:
        return
    artwork_width = spec.width_mm + 2 * spec.bleed_mm
    artwork_height = spec.height_mm + 2 * spec.bleed_mm
    _validate_safe_area_box(
        spec,
        report,
        "Raster content",
        (
            min_x * artwork_width / image.width,
            min_y * artwork_height / image.height,
            (max_x + 1) * artwork_width / image.width,
            (max_y + 1) * artwork_height / image.height,
        ),
    )


def _validate_svg_safe_area(
    spec: LabelSpec, text: str, width_mm: float, height_mm: float, report: Report
) -> None:
    if spec.safe_area_mm == 0:
        return
    report.checks.append("safe-area")
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError as error:
        report.add("SAFE_AREA_UNAVAILABLE", "error", f"Could not parse SVG geometry: {error}")
        return
    try:
        view_box = _svg_view_box(root.get("viewBox"), width_mm, height_mm)
    except ValueError as error:
        report.add("SAFE_AREA_UNAVAILABLE", "error", f"Could not inspect SVG geometry: {error}")
        return
    for element in root.iter():
        tag = element.tag.rsplit("}", 1)[-1]
        if tag in {"svg", "defs", "title", "desc", "metadata"}:
            continue
        if element.get("transform"):
            report.add("SAFE_AREA_UNAVAILABLE", "error", f"Cannot inspect transformed SVG {tag} element")
            continue
        if tag == "text" and "".join(element.itertext()).strip():
            box = _svg_text_box(element, view_box)
        elif tag in {"image", "rect"}:
            box = _svg_rect_box(element, view_box)
            if tag == "rect" and box == (0.0, 0.0, width_mm, height_mm):
                continue
        elif tag in {"g", "style", "clipPath", "mask", "linearGradient", "radialGradient", "stop"}:
            continue
        else:
            report.add("SAFE_AREA_UNAVAILABLE", "error", f"Cannot inspect SVG {tag} geometry")
            continue
        if box is None:
            report.add("SAFE_AREA_UNAVAILABLE", "error", f"Cannot inspect SVG {tag} geometry")
        else:
            _validate_safe_area_box(spec, report, f"SVG {tag}", box)


def _svg_view_box(
    value: str | None, width_mm: float, height_mm: float
) -> tuple[float, float, float, float, float, float]:
    if value is None:
        return (0.0, 0.0, width_mm, height_mm, 1.0, 1.0)
    values = value.replace(",", " ").split()
    if len(values) != 4:
        raise ValueError("SVG viewBox must contain four numbers")
    x, y, width, height = (float(item) for item in values)
    if width <= 0 or height <= 0:
        raise ValueError("SVG viewBox dimensions must be positive")
    return (x, y, width, height, width_mm / width, height_mm / height)


def _svg_coordinate(
    value: str | None, axis: int, view_box: tuple[float, float, float, float, float, float]
) -> float | None:
    if value is None:
        return None
    match = re.fullmatch(r"\s*([0-9.]+)\s*(mm|cm|in|pt|px)?\s*", value)
    if not match:
        return None
    amount = float(match.group(1))
    unit = match.group(2)
    if unit:
        return amount * {"mm": 1, "cm": 10, "in": 25.4, "pt": MM_PER_POINT, "px": MM_PER_SVG_PIXEL}[unit]
    origin = view_box[axis]
    return (amount - origin) * view_box[4 + axis]


def _svg_rect_box(
    element: ElementTree.Element[str], view_box: tuple[float, float, float, float, float, float]
) -> tuple[float, float, float, float] | None:
    x = _svg_coordinate(element.get("x", "0"), 0, view_box)
    y = _svg_coordinate(element.get("y", "0"), 1, view_box)
    width = _svg_coordinate(element.get("width"), 0, view_box)
    height = _svg_coordinate(element.get("height"), 1, view_box)
    if None in (x, y, width, height):
        return None
    return (x, y, x + width, y + height)


def _svg_text_box(
    element: ElementTree.Element[str], view_box: tuple[float, float, float, float, float, float]
) -> tuple[float, float, float, float] | None:
    x = _svg_coordinate((element.get("x") or "").split()[0], 0, view_box)
    y = _svg_coordinate((element.get("y") or "").split()[0], 1, view_box)
    font_size = _svg_coordinate(element.get("font-size", "16px"), 1, view_box)
    if None in (x, y, font_size):
        return None
    content = "".join(element.itertext()).strip()
    width = font_size * len(content) * 0.6
    if element.get("text-anchor") == "middle":
        x -= width / 2
    elif element.get("text-anchor") == "end":
        x -= width
    return (x, y - font_size, x + width, y)


def _validate_pdf_safe_area(spec: LabelSpec, page, report: Report) -> None:
    if spec.safe_area_mm == 0:
        return
    report.checks.append("safe-area")
    blocks = page.get_text("dict").get("blocks", [])
    for block in blocks:
        if block.get("type") not in {0, 1} or "bbox" not in block:
            continue
        _validate_safe_area_box(
            spec, report, "PDF text" if block["type"] == 0 else "PDF image", _pdf_box_mm(block["bbox"])
        )
    for drawing in page.get_drawings():
        box = _pdf_box_mm(drawing["rect"])
        if box != (0.0, 0.0, page.rect.width * MM_PER_POINT, page.rect.height * MM_PER_POINT):
            _validate_safe_area_box(spec, report, "PDF vector drawing", box)


def _pdf_box_mm(rect) -> tuple[float, float, float, float]:
    return tuple(value * MM_PER_POINT for value in rect)


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
