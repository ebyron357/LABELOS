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
    report.metadata["spec"] = _spec_metadata(spec)
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


def _spec_metadata(spec: LabelSpec) -> dict[str, object]:
    """Return a serializable, package-local representation of the validated configuration."""
    return {
        "artwork": spec.artwork.name,
        "width_mm": spec.width_mm,
        "height_mm": spec.height_mm,
        "trim_mm": spec.trim_mm,
        "bleed_mm": spec.bleed_mm,
        "safe_area_mm": spec.safe_area_mm,
        "min_dpi": spec.min_dpi,
        "required_copy": list(spec.required_copy),
        "barcode_value": spec.barcode_value,
        "qr_value": spec.qr_value,
    }


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
    except (OSError, RuntimeError, ValueError) as error:
        report.add("PDF_INVALID", "error", f"Could not read PDF artwork: {error}")
        return ""
    try:
        if document.page_count != 1:
            report.add("PDF_PAGE_COUNT", "error", f"Artwork must contain one page, found {document.page_count}")
            return ""
        page = document[0]
        _validate_physical_size(spec, page.rect.width * MM_PER_POINT, page.rect.height * MM_PER_POINT, report)
        _validate_pdf_safe_area(spec, page, report)
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


def _safe_bounds(spec: LabelSpec) -> tuple[float, float, float, float]:
    """Return the permitted artwork bounds in mm, measured from the bleed edge."""
    inset = spec.bleed_mm + spec.safe_area_mm
    return (
        inset,
        inset,
        spec.width_mm + 2 * spec.bleed_mm - inset,
        spec.height_mm + 2 * spec.bleed_mm - inset,
    )


def _validate_bounds(
    report: Report, bounds: tuple[float, float, float, float], source: str
) -> None:
    left, top, right, bottom = bounds
    safe_left, safe_top, safe_right, safe_bottom = report.metadata["_safe_bounds"]
    if left < safe_left or top < safe_top or right > safe_right or bottom > safe_bottom:
        report.add(
            "SAFE_AREA_VIOLATION",
            "error",
            (
                f"{source} at {left:.2f},{top:.2f}–{right:.2f},{bottom:.2f} mm "
                f"extends outside the safe area"
            ),
        )


def _safe_area_setup(spec: LabelSpec, report: Report) -> bool:
    if not spec.safe_area_mm:
        return False
    report.checks.append("safe-area")
    report.metadata["_safe_bounds"] = _safe_bounds(spec)
    return True


def _safe_area_finish(report: Report) -> None:
    report.metadata.pop("_safe_bounds", None)


def _validate_png_safe_area(spec: LabelSpec, report: Report) -> None:
    if not _safe_area_setup(spec, report):
        return
    try:
        from PIL import Image, ImageChops

        with Image.open(spec.artwork) as image:
            rgba = image.convert("RGBA")
            substrate = Image.new("RGBA", rgba.size, "white")
            rendered = Image.alpha_composite(substrate, rgba).convert("RGB")
            occupied = ImageChops.difference(rendered, Image.new("RGB", rgba.size, "white")).getbbox()
            if occupied is not None:
                left, top, right, bottom = occupied
                width_mm = spec.width_mm + 2 * spec.bleed_mm
                height_mm = spec.height_mm + 2 * spec.bleed_mm
                _validate_bounds(
                    report,
                    (
                        left * width_mm / image.width,
                        top * height_mm / image.height,
                        right * width_mm / image.width,
                        bottom * height_mm / image.height,
                    ),
                    "Non-white PNG content",
                )
    except (OSError, ValueError) as error:
        report.add("PNG_INVALID", "error", f"Could not inspect PNG safe area: {error}")
    finally:
        _safe_area_finish(report)


def _validate_svg_safe_area(
    spec: LabelSpec, text: str, width_mm: float | None, height_mm: float | None, report: Report
) -> None:
    if not _safe_area_setup(spec, report):
        return
    try:
        if width_mm is None or height_mm is None:
            raise ValueError("SVG physical dimensions are required")
        root = ET.fromstring(text)
        view_box = root.get("viewBox")
        if not view_box:
            raise ValueError("SVG viewBox is required")
        values = [float(value) for value in re.split(r"[\s,]+", view_box.strip())]
        if len(values) != 4 or values[2] <= 0 or values[3] <= 0:
            raise ValueError("SVG viewBox must contain four positive values")
        origin_x, origin_y, view_width, view_height = values
        for element in root.iter():
            if element.get("transform"):
                raise ValueError("transformed SVG geometry is not supported")
            tag = element.tag.rsplit("}", 1)[-1]
            if tag not in {"rect", "image", "text"}:
                continue
            if tag == "rect" and _svg_is_white_fill(element.get("fill")):
                continue
            x = _svg_number(element.get("x", "0"))
            y = _svg_number(element.get("y", "0"))
            if tag == "text":
                item = (x, y, x, y)
            else:
                item = (x, y, x + _svg_number(element.get("width")), y + _svg_number(element.get("height")))
            _validate_bounds(
                report,
                (
                    (item[0] - origin_x) * width_mm / view_width,
                    (item[1] - origin_y) * height_mm / view_height,
                    (item[2] - origin_x) * width_mm / view_width,
                    (item[3] - origin_y) * height_mm / view_height,
                ),
                f"SVG {tag}",
            )
    except (ET.ParseError, ValueError) as error:
        report.add("SAFE_AREA_UNCHECKABLE", "error", f"Could not inspect SVG safe area: {error}")
    finally:
        _safe_area_finish(report)


def _svg_number(value: str | None) -> float:
    if value is None:
        raise ValueError("SVG geometry attribute is missing")
    match = re.fullmatch(r"\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*", value)
    if not match:
        raise ValueError(f"SVG geometry value is unsupported: {value!r}")
    return float(match.group(1))


def _svg_is_white_fill(value: str | None) -> bool:
    return value is not None and value.strip().lower() in {"#fff", "#ffffff", "white"}


def _validate_pdf_safe_area(spec: LabelSpec, page, report: Report) -> None:
    if not _safe_area_setup(spec, report):
        return
    try:
        boxes = [block[:4] for block in page.get_text("blocks")]
        for image in page.get_images(full=True):
            boxes.extend(tuple(rect) for rect in page.get_image_rects(image[0]))
        boxes.extend(tuple(drawing["rect"]) for drawing in page.get_drawings())
        for left, top, right, bottom in boxes:
            _validate_bounds(
                report,
                (left * MM_PER_POINT, top * MM_PER_POINT, right * MM_PER_POINT, bottom * MM_PER_POINT),
                "PDF content",
            )
    except (RuntimeError, ValueError) as error:
        report.add("SAFE_AREA_UNCHECKABLE", "error", f"Could not inspect PDF safe area: {error}")
    finally:
        _safe_area_finish(report)


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
