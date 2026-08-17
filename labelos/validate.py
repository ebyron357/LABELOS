"""Artwork validators. Optional readers are reported, never silently skipped."""

from __future__ import annotations

import base64
import re
import struct
from collections.abc import Callable
from io import BytesIO
from pathlib import Path
from urllib.parse import unquote_to_bytes
from xml.etree import ElementTree

from .models import LabelSpec, Report

MM_PER_POINT = 25.4 / 72
MM_PER_CSS_PIXEL = 25.4 / 96


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
        report.add("SVG_INVALID", "error", f"SVG is not valid XML: {error}")
        return text
    if _local_name(root.tag) != "svg":
        report.add("SVG_INVALID", "error", "No SVG root element found")
        return text
    width, height = (_svg_length_mm(root.get("width")), _svg_length_mm(root.get("height")))
    report.checks.extend(["format:svg", "dimensions"])
    if width is None or height is None:
        report.add("SVG_DIMENSIONS_MISSING", "error", "SVG width and height must use physical units")
    else:
        _validate_physical_size(spec, width, height, report)
        _validate_svg_embedded_rasters(spec, report, root, width, height)
    return text


def _svg_length_mm(value: str | None) -> float | None:
    if value is None:
        return None
    match = re.fullmatch(r"\s*([0-9.]+)\s*(mm|cm|in|pt)\s*", value, re.IGNORECASE)
    if not match:
        return None
    value, unit = float(match.group(1)), match.group(2).lower()
    return value * {"mm": 1, "cm": 10, "in": 25.4, "pt": MM_PER_POINT}[unit]


def _svg_embedded_raster_data(href: str) -> bytes | None:
    if not href.startswith("data:image/"):
        return None
    try:
        header, payload = href.split(",", 1)
        if header.lower().startswith("data:image/svg"):
            return None
        return base64.b64decode(payload, validate=True) if ";base64" in header.lower() else unquote_to_bytes(payload)
    except (ValueError, base64.binascii.Error) as error:
        raise ValueError(f"invalid data URI: {error}") from error


def _svg_image_display_mm(
    image: ElementTree.Element, root: ElementTree.Element, width_mm: float, height_mm: float
) -> tuple[float, float]:
    image_width = _svg_length_or_user_units(image.get("width"))
    image_height = _svg_length_or_user_units(image.get("height"))
    if image_width is None or image_height is None:
        raise ValueError("image width and height are required")
    image_width_value, image_width_unit = image_width
    image_height_value, image_height_unit = image_height
    if image_width_unit is not None and image_height_unit is not None:
        return image_width_value, image_height_value

    view_box = root.get("viewBox")
    if view_box:
        try:
            _, _, view_box_width, view_box_height = (float(value) for value in view_box.replace(",", " ").split())
        except ValueError as error:
            raise ValueError("SVG viewBox must contain four numeric values") from error
        if view_box_width <= 0 or view_box_height <= 0:
            raise ValueError("SVG viewBox dimensions must be positive")
        scale_x, scale_y = width_mm / view_box_width, height_mm / view_box_height
        preserve = root.get("preserveAspectRatio", "").lower()
        if "none" not in preserve:
            scale = max(scale_x, scale_y) if "slice" in preserve else min(scale_x, scale_y)
            scale_x = scale_y = scale
    else:
        scale_x = scale_y = MM_PER_CSS_PIXEL

    return (
        image_width_value if image_width_unit is not None else image_width_value * scale_x,
        image_height_value if image_height_unit is not None else image_height_value * scale_y,
    )


def _svg_length_or_user_units(value: str | None) -> tuple[float, str | None] | None:
    if value is None:
        return None
    match = re.fullmatch(r"\s*([0-9.]+)\s*(mm|cm|in|pt|px)?\s*", value, re.IGNORECASE)
    if not match:
        return None
    number, unit = float(match.group(1)), match.group(2)
    if number <= 0:
        return None
    if unit is None or unit.lower() == "px":
        return number, None
    return number * {"mm": 1, "cm": 10, "in": 25.4, "pt": MM_PER_POINT}[unit.lower()], unit


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _validate_svg_embedded_rasters(
    spec: LabelSpec, report: Report, root: ElementTree.Element, width_mm: float, height_mm: float
) -> None:
    images = [element for element in root.iter() if _local_name(element.tag) == "image"]
    if not images:
        return
    report.checks.append("svg-embedded-raster-resolution")
    inspected_images = []
    for index, image in enumerate(images, start=1):
        href = image.get("href") or image.get("{http://www.w3.org/1999/xlink}href")
        if href is None:
            report.add("SVG_EMBEDDED_IMAGE_INSPECTION_FAILED", "error", f"Embedded image {index} has no href")
            continue
        try:
            data = _svg_embedded_raster_data(href)
            if data is None:
                continue
            from PIL import Image

            with Image.open(BytesIO(data)) as raster:
                pixels = raster.size
            display_width, display_height = _svg_image_display_mm(image, root, width_mm, height_mm)
            effective_dpi = min(
                pixels[0] / (display_width / 25.4),
                pixels[1] / (display_height / 25.4),
            )
            inspected_images.append(
                {
                    "index": index,
                    "pixels": {"width": pixels[0], "height": pixels[1]},
                    "display_mm": {"width": round(display_width, 3), "height": round(display_height, 3)},
                    "dpi": round(effective_dpi, 2),
                }
            )
            if effective_dpi < spec.min_dpi:
                report.add(
                    "SVG_EMBEDDED_IMAGE_DPI_TOO_LOW",
                    "error",
                    f"Embedded image {index} has effective resolution {effective_dpi:.1f} DPI; "
                    f"minimum is {spec.min_dpi} DPI",
                )
        except (ImportError, OSError, ValueError) as error:
            report.add(
                "SVG_EMBEDDED_IMAGE_INSPECTION_FAILED",
                "error",
                f"Could not inspect embedded image {index}: {error}",
            )
    if inspected_images:
        report.metadata["svg_embedded_images"] = inspected_images


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
