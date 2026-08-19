"""Artwork validators. Optional readers are reported, never silently skipped."""

from __future__ import annotations

import base64
import re
import struct
import zlib
from collections.abc import Callable
from io import BytesIO
from pathlib import Path, PurePosixPath
from urllib.parse import unquote_to_bytes
from xml.etree import ElementTree

from .models import LabelSpec, Report
from .preflight import get_preflight_adapter

MM_PER_POINT = 25.4 / 72
MM_PER_CSS_PIXEL = 25.4 / 96
SAFE_AREA_RENDER_DPI = 300
_SVG_DOCTYPE_RE = re.compile(r"<!DOCTYPE|<!ENTITY", re.IGNORECASE)


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
    report.metadata["preflight"] = get_preflight_adapter().run(str(spec.artwork)).to_dict()
    return report


def _validate_png(spec: LabelSpec, report: Report) -> str:
    data = spec.artwork.read_bytes()
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n":
        report.add("PNG_INVALID", "error", "File is not a valid PNG")
        return ""
    if not _png_image_data_is_readable(spec.artwork, report):
        return ""
    width, height = struct.unpack(">II", data[16:24])
    dpi = _png_dpi(data)
    report.checks.extend(["format:png", "dimensions", "raster-resolution"])
    report.metadata["pixels"] = {"width": width, "height": height}
    _validate_pixel_dimensions(spec, width, height, dpi, report)
    return ""


def _png_image_data_is_readable(artwork: Path, report: Report) -> bool:
    """Decode the PNG body so a valid header cannot certify unreadable artwork."""

    try:
        from PIL import Image
    except ImportError:
        report.add("PNG_READER_UNAVAILABLE", "error", "Install Pillow to inspect PNG artwork")
        return False
    try:
        with Image.open(artwork) as image:
            if image.format != "PNG":
                raise ValueError("file does not decode as PNG")
            image.load()
    except Image.DecompressionBombError as error:
        report.add("PNG_INVALID", "error", f"PNG image data is unreasonably large: {error}")
        return False
    except (OSError, SyntaxError, ValueError, zlib.error) as error:
        report.add("PNG_INVALID", "error", f"PNG image data could not be decoded: {error}")
        return False
    return True


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
    if _SVG_DOCTYPE_RE.search(text):
        # Entity-substituted content is not literal label text: it can silently satisfy
        # required-copy checks and expand without bound. Reject before parsing.
        report.add(
            "SVG_UNSAFE_XML",
            "error",
            "SVG contains a DOCTYPE or entity declaration; flatten it before validation",
        )
        return ""
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
    number, unit = float(match.group(1)), match.group(2).lower()
    return number * {"mm": 1, "cm": 10, "in": 25.4, "pt": MM_PER_POINT}[unit]


def _svg_embedded_raster_data(href: str) -> bytes | None:
    if not href.startswith("data:image/"):
        return None
    try:
        header, payload = href.split(",", 1)
        if header.lower().startswith("data:image/svg"):
            return None
        if ";base64" in header.lower():
            return base64.b64decode(payload, validate=True)
        return unquote_to_bytes(payload)
    except (ValueError, base64.binascii.Error) as error:
        raise ValueError(f"invalid data URI: {error}") from error


def _resolve_svg_linked_raster(svg_path: Path, href: str) -> tuple[Path, str]:
    """Resolve a local SVG image href without permitting package escape routes."""

    if not href or "\\" in href or "://" in href or href.startswith("file:"):
        raise ValueError("image href must be a local relative file path")
    path = PurePosixPath(href)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("image href must stay under the SVG directory")

    root = svg_path.parent.resolve()
    candidate = root
    for part in path.parts:
        if part in {"", "."}:
            continue
        candidate = candidate / part
        if candidate.is_symlink():
            raise ValueError("image href must not use a symbolic link")
    if not candidate.is_file():
        raise ValueError("image href does not name a regular file")

    resolved = candidate.resolve(strict=True)
    try:
        relative = resolved.relative_to(root)
    except ValueError as error:
        raise ValueError("image href must stay under the SVG directory") from error
    return resolved, relative.as_posix()


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
            _, _, view_box_width, view_box_height = (
                float(value) for value in view_box.replace(",", " ").split()
            )
        except ValueError as error:
            raise ValueError("SVG viewBox must contain four numeric values") from error
        if view_box_width <= 0 or view_box_height <= 0:
            raise ValueError("SVG viewBox dimensions must be positive")
        scale_x, scale_y = width_mm / view_box_width, height_mm / view_box_height
        preserve = (root.get("preserveAspectRatio") or "").lower()
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
    report.checks.append("svg-raster-resolution")
    inspected_images = []
    linked_images = []
    for index, image in enumerate(images, start=1):
        href = image.get("href") or image.get("{http://www.w3.org/1999/xlink}href")
        if href is None:
            report.add("SVG_RASTER_IMAGE_INSPECTION_FAILED", "error", f"Raster image {index} has no href")
            continue
        try:
            data = _svg_embedded_raster_data(href)
            if data is None and href.lower().startswith("data:image/svg"):
                continue
            from PIL import Image

            source: dict[str, str] = {"kind": "embedded"}
            raster_source = BytesIO(data) if data is not None else None
            if raster_source is None:
                linked_path, relative_path = _resolve_svg_linked_raster(spec.artwork, href)
                raster_source = linked_path
                source = {"kind": "linked", "file": relative_path}
            with Image.open(raster_source) as raster:
                raster.load()
                pixels = raster.size
            display_width, display_height = _svg_image_display_mm(image, root, width_mm, height_mm)
            effective_dpi = min(
                pixels[0] / (display_width / 25.4),
                pixels[1] / (display_height / 25.4),
            )
            metadata = {
                "index": index,
                **source,
                "pixels": {"width": pixels[0], "height": pixels[1]},
                "display_mm": {"width": round(display_width, 3), "height": round(display_height, 3)},
                "dpi": round(effective_dpi, 2),
            }
            if data is None:
                linked_images.append(metadata)
            else:
                inspected_images.append(metadata)
            if effective_dpi < spec.min_dpi:
                report.add(
                    "SVG_LINKED_IMAGE_DPI_TOO_LOW" if data is None else "SVG_EMBEDDED_IMAGE_DPI_TOO_LOW",
                    "error",
                    f"{'Linked' if data is None else 'Embedded'} image {index} has effective resolution "
                    f"{effective_dpi:.1f} DPI; "
                    f"minimum is {spec.min_dpi} DPI",
                )
        except (ImportError, OSError, ValueError) as error:
            report.add(
                "SVG_LINKED_IMAGE_INSPECTION_FAILED"
                if not href.startswith("data:image/")
                else "SVG_EMBEDDED_IMAGE_INSPECTION_FAILED",
                "error",
                f"Could not inspect {'linked' if not href.startswith('data:image/') else 'embedded'} "
                f"image {index}: {error}",
            )
    if inspected_images:
        report.metadata["svg_embedded_images"] = inspected_images
    if linked_images:
        report.metadata["svg_linked_images"] = linked_images


def _pdf_open_errors() -> tuple[type[BaseException], ...]:
    errors: tuple[type[BaseException], ...] = (OSError, RuntimeError, ValueError)
    try:
        import pymupdf
    except ImportError:
        return errors
    file_error = getattr(pymupdf, "FileDataError", None)
    if isinstance(file_error, type) and issubclass(file_error, BaseException):
        return (*errors, file_error)
    return errors


def _validate_pdf(spec: LabelSpec, report: Report) -> str:
    try:
        import pymupdf
    except ImportError:
        report.add("PDF_READER_UNAVAILABLE", "error", "Install PyMuPDF to inspect PDF artwork")
        return ""
    try:
        document = pymupdf.open(spec.artwork)
    except _pdf_open_errors() as error:
        report.add("PDF_INVALID", "error", f"Could not open PDF artwork: {error}")
        return ""
    try:
        if document.is_encrypted:
            report.add("PDF_INVALID", "error", "Encrypted PDF artwork cannot be inspected")
            return ""
        if document.page_count != 1:
            report.add("PDF_PAGE_COUNT", "error", f"Artwork must contain one page, found {document.page_count}")
            return ""
        page = document[0]
        _validate_physical_size(
            spec, page.rect.width * MM_PER_POINT, page.rect.height * MM_PER_POINT, report
        )
        text = page.get_text()
        report.checks.extend(["format:pdf", "dimensions", "pdf-readable"])
        report.metadata["pdf"] = {
            "pages": document.page_count,
            "fonts": len(page.get_fonts()),
            "rotation": page.rotation,
        }
        if not page.get_fonts():
            report.add("PDF_NO_FONTS", "warning", "PDF contains no embedded font resources")
        _validate_pdf_image_resolution(document, page, spec, report)
        return text
    except _pdf_open_errors() as error:
        report.add("PDF_INVALID", "error", f"Could not inspect PDF artwork: {error}")
        return ""
    finally:
        document.close()


def _validate_pdf_image_resolution(document, page, spec: LabelSpec, report: Report) -> None:
    """Check the effective resolution of every raster image placed on a PDF page."""

    resolutions = []
    images: list[dict[str, float | int]] = []
    for image in page.get_images(full=True):
        xref = image[0]
        try:
            extracted = document.extract_image(xref)
            width, height = extracted["width"], extracted["height"]
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
            images.append(
                {"xref": xref, "dpi": round(dpi, 2), "width_px": width, "height_px": height}
            )
            if dpi < spec.min_dpi:
                report.add(
                    "PDF_IMAGE_DPI_TOO_LOW",
                    "error",
                    f"Embedded image {xref} has effective resolution {dpi:.1f} DPI; "
                    f"expected at least {spec.min_dpi} DPI",
                )
    if resolutions:
        report.checks.append("pdf-image-resolution")
        report.metadata["pdf"]["embedded_image_dpi"] = resolutions
        report.metadata["pdf"]["images"] = images


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
    if not spec.safe_area_mm:
        return
    blocking = {
        "SVG_INVALID",
        "SVG_UNSAFE_XML",
        "PNG_INVALID",
        "PNG_READER_UNAVAILABLE",
        "PDF_INVALID",
        "PDF_PAGE_COUNT",
    }
    if any(issue.code in blocking for issue in report.issues):
        return
    report.checks.append("safe-area")
    suffix = spec.artwork.suffix.lower()
    try:
        if suffix == ".png":
            bounds = _png_occupied_bounds_mm(spec, report)
        else:
            bounds = _rendered_bounds_mm(spec.artwork)
    except ImportError:
        report.add(
            "SAFE_AREA_UNCHECKABLE",
            "error",
            "Install Pillow and PyMuPDF to inspect artwork safe areas",
        )
        return
    except (OSError, RuntimeError, ValueError) as error:
        report.add("SAFE_AREA_UNCHECKABLE", "error", f"Could not inspect artwork safe area: {error}")
        return
    if bounds is not None and _outside_safe_area(bounds, spec):
        report.add(
            "SAFE_AREA_VIOLATION",
            "error",
            "Visible artwork extends outside the trim plus safe-area inset",
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
    return x0 < left or y0 < top or x1 > right or y1 > bottom


def _png_occupied_bounds_mm(spec: LabelSpec, report: Report) -> tuple[float, float, float, float] | None:
    from PIL import Image

    try:
        with Image.open(spec.artwork) as image:
            return _occupied_bounds_mm(
                image.convert("RGBA"),
                spec.width_mm + 2 * spec.bleed_mm,
                spec.height_mm + 2 * spec.bleed_mm,
            )
    except (OSError, ValueError) as error:
        report.add("PNG_INVALID", "error", f"Could not inspect PNG safe area: {error}")
        return None


def _rendered_bounds_mm(artwork: Path) -> tuple[float, float, float, float] | None:
    import pymupdf
    from PIL import Image

    document = pymupdf.open(artwork)
    try:
        if document.page_count != 1:
            raise ValueError(f"Expected one rendered page, found {document.page_count}")
        page = document[0]
        pixmap = page.get_pixmap(dpi=SAFE_AREA_RENDER_DPI, alpha=True)
        image = Image.open(BytesIO(pixmap.tobytes("png"))).convert("RGBA")
        return _occupied_bounds_mm(image, page.rect.width * MM_PER_POINT, page.rect.height * MM_PER_POINT)
    finally:
        document.close()


def _occupied_bounds_mm(image, width_mm: float, height_mm: float) -> tuple[float, float, float, float] | None:
    from PIL import Image, ImageChops

    white = Image.new("RGBA", image.size, "white")
    rendered = Image.alpha_composite(white, image).convert("RGB")
    occupied = ImageChops.difference(rendered, Image.new("RGB", image.size, "white")).getbbox()
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
        if expected and not _code_matches(expected, decoded):
            report.add("CODE_VALUE_MISMATCH", "error", f"Expected {kind} value not decoded: {expected!r}")


def _code_matches(expected: str, decoded: set[str]) -> bool:
    if expected in decoded:
        return True
    # UPC-A is frequently reported as EAN-13 with a leading zero.
    if expected.isdigit() and len(expected) == 12 and f"0{expected}" in decoded:
        return True
    return expected.isdigit() and len(expected) == 13 and expected.startswith("0") and expected[1:] in decoded


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
