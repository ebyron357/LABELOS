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
    if not report.passed:
        _record_spec_metadata(spec, report)
        return report
    _validate_required_copy(spec, text, report)
    _validate_codes(spec, report)
    _validate_safe_area(spec, report)
    _record_spec_metadata(spec, report)
    return report


def _record_spec_metadata(spec: LabelSpec, report: Report) -> None:
    report.metadata["spec"] = {
        "width_mm": spec.width_mm,
        "height_mm": spec.height_mm,
        "bleed_mm": spec.bleed_mm,
        "trim_mm": spec.trim_mm,
        "safe_area_mm": spec.safe_area_mm,
        "min_dpi": spec.min_dpi,
    }


def _validate_png(spec: LabelSpec, report: Report) -> str:
    data = spec.artwork.read_bytes()
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n":
        report.add("PNG_INVALID", "error", "File is not a valid PNG")
        return ""
    width, height = struct.unpack(">II", data[16:24])
    try:
        from PIL import Image
    except ImportError:
        report.add("PNG_READER_UNAVAILABLE", "error", "Install Pillow to inspect PNG artwork")
        return ""
    try:
        with Image.open(spec.artwork) as image:
            if image.format != "PNG":
                raise ValueError("Pillow did not identify the file as PNG")
            image.verify()
    except (OSError, SyntaxError, ValueError) as error:
        report.add("PNG_INVALID", "error", f"PNG cannot be decoded: {error}")
        return ""
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
    if "<!DOCTYPE" in text.upper():
        report.add("SVG_INVALID", "error", "SVG document type declarations are not allowed")
        return text
    try:
        document = ElementTree.fromstring(text)
    except ElementTree.ParseError as error:
        report.add("SVG_INVALID", "error", f"SVG cannot be parsed: {error}")
        return text
    if not document.tag.lower().endswith("svg"):
        report.add("SVG_INVALID", "error", "SVG root element must be svg")
        return text
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
    except (OSError, RuntimeError, ValueError) as error:
        report.add("PDF_INVALID", "error", f"Could not open PDF artwork: {error}")
        return ""
    try:
        if document.page_count != 1:
            report.add("PDF_PAGE_COUNT", "error", f"Artwork must contain one page, found {document.page_count}")
            return ""
        page = document[0]
        _validate_physical_size(spec, page.rect.width * MM_PER_POINT, page.rect.height * MM_PER_POINT, report)
        text = page.get_text()
        report.checks.extend(["format:pdf", "dimensions", "pdf-readable", "raster-resolution"])
        report.metadata["pdf"] = {"pages": document.page_count, "fonts": len(page.get_fonts())}
        if not page.get_fonts():
            report.add("PDF_NO_FONTS", "warning", "PDF contains no embedded font resources")
        _validate_pdf_image_resolution(document, page, spec, report)
        return text
    except (OSError, RuntimeError, ValueError) as error:
        report.add("PDF_INVALID", "error", f"Could not inspect PDF artwork: {error}")
        return ""
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


def _validate_pdf_image_resolution(document, page, spec: LabelSpec, report: Report) -> None:
    """Check the effective resolution of every raster image placed on a PDF page."""
    resolutions = []
    for image in page.get_images(full=True):
        xref = image[0]
        try:
            pixmap = document.extract_image(xref)
            width, height = pixmap["width"], pixmap["height"]
            rectangles = page.get_image_rects(xref)
        except (KeyError, RuntimeError, ValueError) as error:
            report.add(
                "PDF_IMAGE_INSPECTION_FAILED",
                "error",
                f"Could not inspect embedded image {xref}: {error}",
            )
            continue
        for rectangle in rectangles:
            if rectangle.width <= 0 or rectangle.height <= 0:
                report.add(
                    "PDF_IMAGE_INSPECTION_FAILED",
                    "error",
                    f"Embedded image {xref} has an invalid placement rectangle",
                )
                continue
            dpi = min(width / (rectangle.width / 72), height / (rectangle.height / 72))
            resolutions.append(round(dpi, 2))
            if dpi < spec.min_dpi:
                report.add(
                    "PDF_IMAGE_DPI_TOO_LOW",
                    "error",
                    f"Embedded image {xref} has effective resolution {dpi:.1f} DPI; "
                    f"expected at least {spec.min_dpi} DPI",
                )
    if resolutions:
        report.metadata["pdf"]["embedded_image_dpi"] = resolutions


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


def _validate_safe_area(spec: LabelSpec, report: Report) -> None:
    """Reject non-background artwork outside the configured trim-safe rectangle."""
    if not spec.safe_area_mm:
        return
    report.checks.append("safe-area")
    try:
        from PIL import Image
    except ImportError:
        report.add("SAFE_AREA_READER_UNAVAILABLE", "error", "Install Pillow to validate the safe area")
        return
    try:
        with _safe_area_image(spec.artwork, Image) as image:
            if _has_transparency(image):
                report.add(
                    "SAFE_AREA_TRANSPARENT",
                    "error",
                    "Artwork has transparency; a safe-area background cannot be determined",
                )
                return
            image = image.convert("RGB")
            background = _corner_background(image)
            if background is None:
                report.add(
                    "SAFE_AREA_BACKGROUND_AMBIGUOUS",
                    "error",
                    "Artwork corners disagree; a safe-area background cannot be determined",
                )
                return
            safe_left = round(
                (spec.bleed_mm + spec.safe_area_mm) / (spec.width_mm + 2 * spec.bleed_mm)
                * image.width
            )
            safe_top = round(
                (spec.bleed_mm + spec.safe_area_mm) / (spec.height_mm + 2 * spec.bleed_mm)
                * image.height
            )
            if safe_left * 2 >= image.width or safe_top * 2 >= image.height:
                report.add("SAFE_AREA_INVALID", "error", "Safe area leaves no rasterized printable area")
                return
            outside = (
                image.crop((0, 0, safe_left, image.height)),
                image.crop((image.width - safe_left, 0, image.width, image.height)),
                image.crop((safe_left, 0, image.width - safe_left, safe_top)),
                image.crop((safe_left, image.height - safe_top, image.width - safe_left, image.height)),
            )
            if any(_contains_non_background(region, background) for region in outside):
                report.add(
                    "SAFE_AREA_VIOLATION",
                    "error",
                    "Non-background artwork extends outside the configured safe area",
                )
    except (ImportError, OSError, RuntimeError, ValueError) as error:
        report.add("SAFE_AREA_RENDER_FAILED", "error", f"Could not inspect safe area: {error}")


def _safe_area_image(artwork: Path, image_module):
    if artwork.suffix.lower() == ".png":
        image = image_module.open(artwork)
        image.load()
        return image
    import pymupdf

    document = pymupdf.open(artwork)
    try:
        if document.page_count < 1:
            raise ValueError("Artwork contains no pages to inspect")
        pixmap = document[0].get_pixmap(dpi=300, alpha=False)
        image = image_module.open(BytesIO(pixmap.tobytes("png")))
        image.load()
        return image
    finally:
        document.close()


def _has_transparency(image) -> bool:
    if "A" not in image.getbands():
        return False
    alpha = image.getchannel("A")
    return alpha.getextrema()[0] < 255


def _corner_background(image) -> tuple[int, int, int] | None:
    corners = (
        image.getpixel((0, 0)),
        image.getpixel((image.width - 1, 0)),
        image.getpixel((0, image.height - 1)),
        image.getpixel((image.width - 1, image.height - 1)),
    )
    background = corners[0]
    if any(_pixel_distance(pixel, background) > 8 for pixel in corners[1:]):
        return None
    return background


def _contains_non_background(image, background: tuple[int, int, int]) -> bool:
    return any(_pixel_distance(pixel, background) > 8 for pixel in image.get_flattened_data())


def _pixel_distance(first: tuple[int, int, int], second: tuple[int, int, int]) -> int:
    return max(abs(component - reference) for component, reference in zip(first, second))


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
