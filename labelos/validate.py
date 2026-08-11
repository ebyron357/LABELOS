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
    """Ensure visible content does not enter the trim-safe exclusion zone."""
    if not spec.safe_area_mm:
        return
    report.checks.append("safe-area")
    suffix = spec.artwork.suffix.lower()
    if suffix == ".png":
        _validate_png_safe_area(spec, report)
    elif suffix == ".svg":
        _validate_svg_safe_area(spec, report)
    elif suffix == ".pdf":
        _validate_pdf_safe_area(spec, report)


def _safe_bounds(spec: LabelSpec) -> tuple[float, float, float, float]:
    left = spec.bleed_mm + spec.safe_area_mm
    top = spec.bleed_mm + spec.safe_area_mm
    return (
        left,
        top,
        spec.width_mm + spec.bleed_mm - spec.safe_area_mm,
        spec.height_mm + spec.bleed_mm - spec.safe_area_mm,
    )


def _outside_safe_area(bounds: tuple[float, float, float, float], spec: LabelSpec) -> bool:
    left, top, right, bottom = _safe_bounds(spec)
    x0, y0, x1, y1 = bounds
    return x0 < left - 0.1 or y0 < top - 0.1 or x1 > right + 0.1 or y1 > bottom + 0.1


def _safe_area_error(report: Report, detail: str) -> None:
    report.add("SAFE_AREA_VIOLATION", "error", f"Visible artwork enters the safe-area exclusion zone: {detail}")


def _validate_png_safe_area(spec: LabelSpec, report: Report) -> None:
    try:
        from PIL import Image

        with Image.open(spec.artwork) as image:
            rgba = image.convert("RGBA")
            width, height = rgba.size
            left, top, right, bottom = _safe_bounds(spec)
            total_width = spec.width_mm + 2 * spec.bleed_mm
            total_height = spec.height_mm + 2 * spec.bleed_mm
            safe_pixels = (
                left / total_width * width,
                top / total_height * height,
                right / total_width * width,
                bottom / total_height * height,
            )
            for y in range(height):
                for x in range(width):
                    red, green, blue, alpha = rgba.getpixel((x, y))
                    if (
                        alpha
                        and (red, green, blue) != (255, 255, 255)
                        and (x < safe_pixels[0] or y < safe_pixels[1] or x >= safe_pixels[2] or y >= safe_pixels[3])
                    ):
                        _safe_area_error(report, f"non-white pixel at {x},{y}")
                        return
    except (ImportError, OSError, ValueError) as error:
        report.add("SAFE_AREA_UNCHECKABLE", "error", f"Could not inspect PNG safe area: {error}")


def _validate_svg_safe_area(spec: LabelSpec, report: Report) -> None:
    try:
        root = ElementTree.parse(spec.artwork).getroot()
    except ElementTree.ParseError as error:
        report.add("SVG_INVALID", "error", f"Invalid SVG XML: {error}")
        return
    view_box = root.get("viewBox", "").replace(",", " ").split()
    if len(view_box) != 4:
        report.add("SAFE_AREA_UNCHECKABLE", "error", "SVG safe-area validation requires a four-value viewBox")
        return
    try:
        view_x, view_y, view_width, view_height = (float(value) for value in view_box)
    except ValueError:
        report.add("SAFE_AREA_UNCHECKABLE", "error", "SVG viewBox must contain numeric values")
        return
    if view_width <= 0 or view_height <= 0:
        report.add("SAFE_AREA_UNCHECKABLE", "error", "SVG viewBox dimensions must be positive")
        return
    if any("transform" in element.attrib for element in root.iter()):
        report.add("SAFE_AREA_UNCHECKABLE", "error", "SVG transforms are not supported for safe-area validation")
        return
    physical_width = spec.width_mm + 2 * spec.bleed_mm
    physical_height = spec.height_mm + 2 * spec.bleed_mm
    supported = {"text", "image", "rect"}
    unsupported_visual = {"circle", "ellipse", "line", "path", "polygon", "polyline", "use"}
    for element in root.iter():
        tag = element.tag.rsplit("}", 1)[-1]
        if tag in unsupported_visual:
            report.add(
                "SAFE_AREA_UNCHECKABLE",
                "error",
                f"SVG {tag} is not supported for safe-area validation",
            )
            return
        if tag not in supported:
            continue
        if tag == "rect" and element.get("fill", "").lower() in {"white", "#fff", "#ffffff"}:
            continue
        try:
            x = float(element.get("x", "0"))
            y = float(element.get("y", "0"))
            width = float(element.get("width", "0"))
            height = float(element.get("height", "0"))
        except ValueError:
            report.add("SAFE_AREA_UNCHECKABLE", "error", f"SVG {tag} has non-numeric bounds")
            return
        if tag == "text":
            if "x" not in element.attrib or "y" not in element.attrib:
                report.add("SAFE_AREA_UNCHECKABLE", "error", "SVG text must provide x and y coordinates")
                return
            bounds = (
                (x - view_x) / view_width * physical_width,
                (y - view_y) / view_height * physical_height,
                (x - view_x) / view_width * physical_width,
                (y - view_y) / view_height * physical_height,
            )
            if _outside_safe_area(bounds, spec):
                _safe_area_error(report, "SVG text anchor")
                return
            continue
        bounds = (
            (x - view_x) / view_width * physical_width,
            (y - view_y) / view_height * physical_height,
            (x + width - view_x) / view_width * physical_width,
            (y + height - view_y) / view_height * physical_height,
        )
        if _outside_safe_area(bounds, spec):
            _safe_area_error(report, f"SVG {tag}")
            return


def _validate_pdf_safe_area(spec: LabelSpec, report: Report) -> None:
    try:
        import pymupdf

        document = pymupdf.open(spec.artwork)
        try:
            if document.page_count != 1:
                return
            page = document[0]
            candidates = [block["bbox"] for block in page.get_text("dict")["blocks"] if "bbox" in block]
            for image in page.get_images(full=True):
                candidates.extend((rect.x0, rect.y0, rect.x1, rect.y1) for rect in page.get_image_rects(image[0]))
            candidates.extend(
                (drawing["rect"].x0, drawing["rect"].y0, drawing["rect"].x1, drawing["rect"].y1)
                for drawing in page.get_drawings()
            )
            for x0, y0, x1, y1 in candidates:
                if _outside_safe_area(
                    (x0 * MM_PER_POINT, y0 * MM_PER_POINT, x1 * MM_PER_POINT, y1 * MM_PER_POINT), spec
                ):
                    _safe_area_error(report, "PDF text, image, or vector")
                    return
        finally:
            document.close()
    except (ImportError, OSError, RuntimeError, ValueError) as error:
        report.add("SAFE_AREA_UNCHECKABLE", "error", f"Could not inspect PDF safe area: {error}")


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
