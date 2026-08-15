"""Artwork validators. Optional readers are reported, never silently skipped."""

from __future__ import annotations

import re
import struct
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
    _validate_safe_area(spec, report)
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


def _validate_safe_area(spec: LabelSpec, report: Report) -> None:
    """Fail when visible artwork occupies the configured bleed and safe-area margin.

    The margin starts at the outside of the full-bleed asset. A uniform background is
    permitted to extend through it; other pixels are treated as printable content.
    """
    if spec.safe_area_mm <= 0:
        return
    if any(issue.severity == "error" for issue in report.issues):
        return
    report.checks.append("safe-area")
    try:
        from PIL import Image

        with _safe_area_image(spec.artwork, Image) as image:
            _inspect_safe_area(spec, image, report)
    except (ImportError, OSError, RuntimeError, ValueError) as error:
        report.add(
            "SAFE_AREA_UNCHECKABLE",
            "error",
            f"Could not inspect the {spec.safe_area_mm:g} mm safe area: {error}",
        )


def _safe_area_image(artwork: Path, image_module):
    """Render supported artwork into a normalized RGB raster for margin inspection."""
    if artwork.suffix.lower() == ".png":
        image = image_module.open(artwork)
        image.load()
    else:
        import pymupdf

        document = pymupdf.open(artwork)
        try:
            if document.page_count != 1:
                raise ValueError(f"expected one page, found {document.page_count}")
            pixmap = document[0].get_pixmap(dpi=300, alpha=False)
            image = image_module.open(BytesIO(pixmap.tobytes("png")))
            image.load()
        finally:
            document.close()
    return image.convert("RGB")


def _inspect_safe_area(spec: LabelSpec, image, report: Report) -> None:
    """Inspect rasterized artwork for non-background pixels in the protected margin."""
    expected_width = spec.width_mm + 2 * spec.bleed_mm
    expected_height = spec.height_mm + 2 * spec.bleed_mm
    margin_x = round(image.width * (spec.bleed_mm + spec.safe_area_mm) / expected_width)
    margin_y = round(image.height * (spec.bleed_mm + spec.safe_area_mm) / expected_height)
    if margin_x < 1 or margin_y < 1 or margin_x * 2 >= image.width or margin_y * 2 >= image.height:
        raise ValueError("safe-area margin cannot be resolved from artwork dimensions")

    pixels = image.load()
    corners = (
        pixels[0, 0],
        pixels[image.width - 1, 0],
        pixels[0, image.height - 1],
        pixels[image.width - 1, image.height - 1],
    )
    background = corners[0]
    if any(_color_distance(background, color) > 12 for color in corners[1:]):
        raise ValueError("artwork edge has no uniform background")

    for y in range(image.height):
        for x in range(image.width):
            if x >= margin_x and x < image.width - margin_x and y >= margin_y and y < image.height - margin_y:
                continue
            if _color_distance(background, pixels[x, y]) > 24:
                report.add(
                    "SAFE_AREA_VIOLATION",
                    "error",
                    f"Non-background artwork appears within {spec.safe_area_mm:g} mm safe area",
                )
                return


def _color_distance(first: tuple[int, int, int], second: tuple[int, int, int]) -> int:
    return max(abs(left - right) for left, right in zip(first, second, strict=True))


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
