import hashlib
import json
import os
import struct
import subprocess
import sys
import zlib
from base64 import b64encode
from io import BytesIO
from pathlib import Path

import barcode
import pymupdf
import pytest
import qrcode
from barcode.writer import ImageWriter
from PIL import Image, ImageDraw

from labelos.cli import main
from labelos.models import LabelSpec
from labelos.package import create_package, verify_package
from labelos.validate import validate

ROOT = Path(__file__).parent.parent


def passing_spec() -> LabelSpec:
    return LabelSpec.from_dict(
        {
            "artwork": "fixtures/passing-label.svg",
            "width_mm": 100,
            "height_mm": 50,
            "bleed_mm": 3,
            "safe_area_mm": 2,
            "required_copy": ["Example Product", "NET 250 g"],
        },
        ROOT,
    )


def test_passing_svg_validates():
    report = validate(passing_spec())
    assert report.passed
    assert report.metadata["artwork_size_mm"] == {"width": 106.0, "height": 56.0}
    assert "safe-area" in report.checks
    assert report.metadata["preflight"]["status"] == "SKIPPED_NOT_CONFIGURED"


def test_missing_copy_fails():
    spec = LabelSpec.from_dict(
        {"artwork": "fixtures/passing-label.svg", "width_mm": 106, "height_mm": 56, "required_copy": ["Absent"]},
        ROOT,
    )
    report = validate(spec)
    assert not report.passed
    assert report.issues[0].code == "REQUIRED_COPY_MISSING"


def test_dimension_mismatch_fails():
    spec = LabelSpec.from_dict(
        {"artwork": "fixtures/passing-label.svg", "width_mm": 100, "height_mm": 50}, ROOT
    )
    assert any(issue.code == "DIMENSIONS_MISMATCH" for issue in validate(spec).issues)


def test_png_safe_area_accepts_artwork_on_boundary(tmp_path):
    artwork = tmp_path / "boundary.png"
    image = Image.new("RGBA", (106, 56), "white")
    ImageDraw.Draw(image).rectangle((5, 5, 14, 14), fill="black")
    image.save(artwork)
    spec = LabelSpec.from_dict(
        {
            "artwork": artwork.name,
            "width_mm": 100,
            "height_mm": 50,
            "bleed_mm": 3,
            "safe_area_mm": 2,
            "min_dpi": 1,
        },
        tmp_path,
    )

    report = validate(spec)

    assert report.passed
    assert "safe-area" in report.checks


def test_png_safe_area_rejects_one_pixel_outside_boundary(tmp_path):
    artwork = tmp_path / "outside.png"
    image = Image.new("RGBA", (106, 56), "white")
    ImageDraw.Draw(image).rectangle((4, 5, 14, 14), fill="black")
    image.save(artwork)
    spec = LabelSpec.from_dict(
        {
            "artwork": artwork.name,
            "width_mm": 100,
            "height_mm": 50,
            "bleed_mm": 3,
            "safe_area_mm": 2,
            "min_dpi": 1,
        },
        tmp_path,
    )

    assert any(issue.code == "SAFE_AREA_VIOLATION" for issue in validate(spec).issues)


def test_png_safe_area_ignores_fully_transparent_pixels(tmp_path):
    artwork = tmp_path / "transparent.png"
    image = Image.new("RGBA", (106, 56), (255, 255, 255, 255))
    image.putpixel((0, 0), (0, 0, 0, 0))
    image.save(artwork)
    spec = LabelSpec.from_dict(
        {
            "artwork": artwork.name,
            "width_mm": 100,
            "height_mm": 50,
            "bleed_mm": 3,
            "safe_area_mm": 2,
            "min_dpi": 1,
        },
        tmp_path,
    )

    assert validate(spec).passed


def test_low_dpi_png_fails(tmp_path):
    artwork = tmp_path / "low-dpi.png"
    Image.new("RGB", (50, 25), "white").save(artwork)
    spec = LabelSpec.from_dict(
        {"artwork": artwork.name, "width_mm": 100, "height_mm": 50, "min_dpi": 300},
        tmp_path,
    )

    report = validate(spec)

    assert not report.passed
    assert any(issue.code == "DPI_TOO_LOW" for issue in report.issues)


def test_malformed_svg_fails_structured(tmp_path):
    artwork = tmp_path / "broken.svg"
    artwork.write_text("<svg><g></svg>", encoding="utf-8")
    spec = LabelSpec.from_dict(
        {"artwork": artwork.name, "width_mm": 100, "height_mm": 50},
        tmp_path,
    )

    assert any(issue.code == "SVG_INVALID" for issue in validate(spec).issues)


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload))


def _png_header(width_px: int, height_px: int) -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", struct.pack(">IIBBBBB", width_px, height_px, 8, 2, 0, 0, 0))
        + _png_chunk(b"pHYs", struct.pack(">IIB", 11811, 11811, 1))
    )


def test_corrupt_png_body_fails_closed(tmp_path):
    """A valid PNG header must not certify artwork whose image data cannot decode."""
    artwork = tmp_path / "corrupt-body.png"
    artwork.write_bytes(
        _png_header(1400, 760)
        + _png_chunk(b"IDAT", b"not zlib compressed scanline data")
        + _png_chunk(b"IEND", b"")
    )
    spec = LabelSpec.from_dict(
        {"artwork": artwork.name, "width_mm": 100, "height_mm": 50, "bleed_mm": 3}, tmp_path
    )

    report = validate(spec)

    assert not report.passed
    assert any(issue.code == "PNG_INVALID" for issue in report.issues)


def test_truncated_png_fails_closed(tmp_path):
    artwork = tmp_path / "truncated.png"
    artwork.write_bytes(_png_header(1400, 760) + b"\x00\x00\x00\x20IDAT")
    spec = LabelSpec.from_dict(
        {"artwork": artwork.name, "width_mm": 100, "height_mm": 50, "bleed_mm": 3}, tmp_path
    )

    report = validate(spec)

    assert not report.passed
    assert any(issue.code == "PNG_INVALID" for issue in report.issues)


def test_svg_doctype_declaration_is_rejected(tmp_path):
    artwork = tmp_path / "doctype.svg"
    artwork.write_text(
        '<?xml version="1.0"?>\n'
        '<!DOCTYPE svg [<!ENTITY a "aaaaaaaaaa">]>\n'
        '<svg xmlns="http://www.w3.org/2000/svg" width="106mm" height="56mm">'
        '<text x="10" y="20">&a;</text></svg>',
        encoding="utf-8",
    )
    spec = LabelSpec.from_dict(
        {"artwork": artwork.name, "width_mm": 100, "height_mm": 50, "bleed_mm": 3}, tmp_path
    )

    report = validate(spec)

    assert not report.passed
    assert [issue.code for issue in report.issues] == ["SVG_UNSAFE_XML"]


def test_svg_entity_cannot_satisfy_required_copy(tmp_path):
    """Required copy must come from label text, not from an XML entity declaration."""
    artwork = tmp_path / "entity-copy.svg"
    artwork.write_text(
        '<?xml version="1.0"?>\n'
        '<!DOCTYPE svg [<!ENTITY claim "CERTIFIED ORGANIC">]>\n'
        '<svg xmlns="http://www.w3.org/2000/svg" width="106mm" height="56mm">'
        '<text x="10" y="20">&claim;</text></svg>',
        encoding="utf-8",
    )
    spec = LabelSpec.from_dict(
        {
            "artwork": artwork.name,
            "width_mm": 100,
            "height_mm": 50,
            "bleed_mm": 3,
            "required_copy": ["CERTIFIED ORGANIC"],
        },
        tmp_path,
    )

    report = validate(spec)

    assert not report.passed
    codes = {issue.code for issue in report.issues}
    assert "SVG_UNSAFE_XML" in codes
    assert "REQUIRED_COPY_MISSING" in codes


def test_malformed_pdf_fails_closed_without_crashing(tmp_path):
    artwork = tmp_path / "malformed.pdf"
    artwork.write_bytes(b"not a PDF")
    spec = LabelSpec.from_dict({"artwork": artwork.name, "width_mm": 100, "height_mm": 50}, tmp_path)

    report = validate(spec)

    assert not report.passed
    assert [issue.code for issue in report.issues] == ["PDF_INVALID"]


def test_package_contains_verified_manifest(tmp_path):
    spec = passing_spec()
    report = validate(spec)
    manifest = create_package(spec, report, tmp_path / "release")
    assert manifest.is_file()
    assert not verify_package(manifest.parent)
    assert json.loads((manifest.parent / "label-spec.json").read_text(encoding="utf-8")) == spec.to_dict(
        artwork="passing-label.svg"
    )
    artwork_path = manifest.parent / "passing-label.svg"
    artwork_path.write_text("x" * artwork_path.stat().st_size, encoding="utf-8")
    assert verify_package(manifest.parent) == ["artwork checksum mismatch: passing-label.svg"]


def test_package_refuses_failed_report(tmp_path):
    spec = LabelSpec.from_dict(
        {"artwork": "fixtures/passing-label.svg", "width_mm": 100, "height_mm": 50},
        ROOT,
    )
    report = validate(spec)
    assert not report.passed
    with pytest.raises(ValueError, match="Refusing to package"):
        create_package(spec, report, tmp_path / "release")


def test_package_rejects_unsafe_extra_filename(tmp_path):
    spec = passing_spec()
    report = validate(spec)
    with pytest.raises(ValueError, match="Unsafe package extra filename"):
        create_package(spec, report, tmp_path / "release", extras={"../secret.json": "{}"})


def test_verify_package_rejects_path_traversal(tmp_path):
    manifest = create_package(passing_spec(), validate(passing_spec()), tmp_path / "release")
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["artwork"]["file"] = "../outside.svg"
    manifest.write_text(json.dumps(data), encoding="utf-8")

    assert verify_package(manifest.parent) == ["artwork file must be a package-relative filename"]


def test_verify_package_rejects_symlink_entries(tmp_path):
    manifest = create_package(passing_spec(), validate(passing_spec()), tmp_path / "release")
    artwork_path = manifest.parent / "passing-label.svg"
    target = tmp_path / "outside.svg"
    target.write_text("outside", encoding="utf-8")
    artwork_path.unlink()
    try:
        artwork_path.symlink_to(target)
    except OSError:
        pytest.skip("symlinks are not permitted in this environment")

    assert verify_package(manifest.parent) == [
        "artwork file is missing or is not a regular file: passing-label.svg"
    ]


def test_verify_package_rejects_byte_count_mismatch(tmp_path):
    manifest = create_package(passing_spec(), validate(passing_spec()), tmp_path / "release")
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["label_spec"]["bytes"] += 1
    manifest.write_text(json.dumps(data), encoding="utf-8")

    assert verify_package(manifest.parent) == ["label_spec byte count mismatch: label-spec.json"]


def test_verify_package_rejects_tampered_validation_report(tmp_path):
    manifest = create_package(passing_spec(), validate(passing_spec()), tmp_path / "release")
    report_path = manifest.parent / "validation-report.json"
    report_data = json.loads(report_path.read_text(encoding="utf-8"))
    report_data["passed"] = False
    report_path.write_text(json.dumps(report_data), encoding="utf-8")
    manifest_data = json.loads(manifest.read_text(encoding="utf-8"))
    manifest_data["validation_report"]["sha256"] = hashlib.sha256(report_path.read_bytes()).hexdigest()
    manifest_data["validation_report"]["bytes"] = report_path.stat().st_size
    manifest_data["validation_report"]["passed"] = False
    manifest.write_text(json.dumps(manifest_data), encoding="utf-8")

    assert verify_package(manifest.parent) == [
        "validation report does not record a passing result",
        "manifest does not record a passing validation result",
    ]


def test_cli_validate_and_package(tmp_path, capsys):
    config = tmp_path / "label.json"
    config.write_text(
        json.dumps(
            {
                "artwork": str(ROOT / "fixtures/passing-label.svg"),
                "width_mm": 106,
                "height_mm": 56,
                "required_copy": ["Example Product"],
            }
        ),
        encoding="utf-8",
    )
    assert main(["validate", str(config), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["passed"]
    package = tmp_path / "release"
    assert main(["package", str(config), str(package)]) == 0
    assert main(["verify-package", str(package)]) == 0


def test_cli_validate_failing_fixture():
    assert main(["validate", str(ROOT / "examples/failing-label.json"), "--json"]) == 1


def test_cli_doctor_reports_callas_unavailable(capsys):
    assert main(["doctor", "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["passed"] is True
    assert result["tools"]["Pillow"]["available"] is True
    assert result["tools"]["PyMuPDF"]["available"] is True
    assert result["tools"]["ZXing-C++"]["available"] is True
    assert result["tools"]["Callas pdfToolbox"]["available"] is False
    assert result["tools"]["Callas pdfToolbox"]["status"] == "SKIPPED_NOT_CONFIGURED"


def test_module_cli_runs_outside_repository(tmp_path):
    environment = {**os.environ, "PYTHONPATH": str(ROOT)}
    result = subprocess.run(
        [sys.executable, "-m", "labelos", "doctor", "--json"],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert json.loads(result.stdout)["passed"] is True


def test_qr_expected_value_is_decoded(tmp_path):
    image = qrcode.make("https://example.test/sku/42")
    artwork = tmp_path / "qr.png"
    image.save(artwork)
    spec = LabelSpec.from_dict(
        {
            "artwork": artwork.name,
            "width_mm": 20,
            "height_mm": 20,
            "min_dpi": 1,
            "qr_value": "https://example.test/sku/42",
        },
        tmp_path,
    )
    report = validate(spec)
    assert report.passed
    assert report.metadata["decoded_values"] == ["https://example.test/sku/42"]


def test_barcode_expected_value_is_decoded(tmp_path):
    value = "LABELOS-12345"
    artwork = Path(
        barcode.get("code128", value, writer=ImageWriter()).save(str(tmp_path / "barcode"))
    )
    spec = LabelSpec.from_dict(
        {
            "artwork": artwork.name,
            "width_mm": 100,
            "height_mm": 100,
            "min_dpi": 1,
            "barcode_value": value,
        },
        tmp_path,
    )
    report = validate(spec)
    assert report.passed
    assert report.metadata["decoded_values"] == [value]


def test_upc_a_matches_ean13_leading_zero():
    from labelos.validate import _code_matches

    assert _code_matches("012345678905", {"0012345678905", "https://example.test"})
    assert _code_matches("0012345678905", {"012345678905"})
    assert not _code_matches("012345678905", {"012345678906"})


def test_qr_expected_value_is_decoded_from_svg(tmp_path):
    value = "https://example.test/svg-qr"
    qr = qrcode.make(value)
    buffer = BytesIO()
    qr.save(buffer, format="PNG")
    artwork = tmp_path / "qr.svg"
    artwork.write_text(
        (
            '<svg xmlns="http://www.w3.org/2000/svg" width="20mm" height="20mm" '
            'viewBox="0 0 20 20">'
            f'<image href="data:image/png;base64,{b64encode(buffer.getvalue()).decode()}" '
            'width="20" height="20"/></svg>'
        ),
        encoding="utf-8",
    )
    spec = LabelSpec.from_dict(
        {"artwork": artwork.name, "width_mm": 20, "height_mm": 20, "qr_value": value}, tmp_path
    )

    report = validate(spec)

    assert report.passed
    assert report.metadata["decoded_values"] == [value]
    assert report.metadata["svg_embedded_images"][0]["dpi"] >= 300


def test_under_resolution_embedded_svg_image_fails(tmp_path):
    image = qrcode.make("https://example.test/low-resolution")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    artwork = tmp_path / "low-resolution.svg"
    artwork.write_text(
        (
            '<svg xmlns="http://www.w3.org/2000/svg" width="100mm" height="100mm" '
            'viewBox="0 0 100 100">'
            f'<image href="data:image/png;base64,{b64encode(buffer.getvalue()).decode()}" '
            'width="100" height="100"/></svg>'
        ),
        encoding="utf-8",
    )
    spec = LabelSpec.from_dict(
        {"artwork": artwork.name, "width_mm": 100, "height_mm": 100, "min_dpi": 300}, tmp_path
    )

    report = validate(spec)

    assert not report.passed
    assert report.metadata["svg_embedded_images"][0]["dpi"] < 300
    assert any(issue.code == "SVG_EMBEDDED_IMAGE_DPI_TOO_LOW" for issue in report.issues)


def test_linked_svg_raster_is_validated_and_packaged(tmp_path):
    assets = tmp_path / "assets"
    assets.mkdir()
    Image.new("RGB", (1200, 1200), "black").save(assets / "seal.png")
    artwork = tmp_path / "linked.svg"
    artwork.write_text(
        (
            '<svg xmlns="http://www.w3.org/2000/svg" width="100mm" height="100mm" '
            'viewBox="0 0 100 100">'
            '<image href="assets/seal.png" x="10" y="10" width="20" height="20"/></svg>'
        ),
        encoding="utf-8",
    )
    spec = LabelSpec.from_dict(
        {"artwork": artwork.name, "width_mm": 100, "height_mm": 100, "min_dpi": 300}, tmp_path
    )

    report = validate(spec)

    assert report.passed
    assert report.metadata["svg_linked_images"][0]["file"] == "assets/seal.png"
    manifest = create_package(spec, report, tmp_path / "release")
    manifest_data = json.loads(manifest.read_text(encoding="utf-8"))
    assert manifest_data["schema_version"] == 2
    assert manifest_data["linked_assets"]["assets/seal.png"]["file"] == "assets/seal.png"
    assert (manifest.parent / "assets" / "seal.png").is_file()
    assert verify_package(manifest.parent) == []


@pytest.mark.parametrize("href", ["../outside.png", "/tmp/outside.png", "https://example.test/image.png"])
def test_unsafe_or_remote_linked_svg_raster_fails_closed(tmp_path, href):
    artwork = tmp_path / "unsafe-linked.svg"
    artwork.write_text(
        (
            '<svg xmlns="http://www.w3.org/2000/svg" width="100mm" height="100mm">'
            f'<image href="{href}" width="20mm" height="20mm"/></svg>'
        ),
        encoding="utf-8",
    )
    spec = LabelSpec.from_dict(
        {"artwork": artwork.name, "width_mm": 100, "height_mm": 100}, tmp_path
    )

    report = validate(spec)

    assert any(issue.code == "SVG_LINKED_IMAGE_INSPECTION_FAILED" for issue in report.issues)


def test_schema_one_package_remains_verifiable(tmp_path):
    manifest = create_package(passing_spec(), validate(passing_spec()), tmp_path / "release")
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["schema_version"] = 1
    data.pop("linked_assets")
    manifest.write_text(json.dumps(data), encoding="utf-8")

    assert verify_package(manifest.parent) == []


def test_barcode_expected_value_is_decoded_from_pdf(tmp_path):
    value = "LABELOS-PDF-12345"
    barcode_path = Path(
        barcode.get("code128", value, writer=ImageWriter()).save(
            str(tmp_path / "barcode"), options={"dpi": 600}
        )
    )
    artwork = tmp_path / "barcode.pdf"
    document = pymupdf.open()
    page = document.new_page(width=100 / (25.4 / 72), height=100 / (25.4 / 72))
    page.insert_image(pymupdf.Rect(25, 50, 250, 150), filename=barcode_path)
    document.save(artwork)
    document.close()
    spec = LabelSpec.from_dict(
        {
            "artwork": artwork.name,
            "width_mm": 100,
            "height_mm": 100,
            "min_dpi": 1,
            "barcode_value": value,
        },
        tmp_path,
    )

    report = validate(spec)

    assert report.passed
    assert report.metadata["decoded_values"] == [value]


def test_pdf_embedded_image_dpi_is_enforced(tmp_path):
    image_path = tmp_path / "source.png"
    Image.new("RGB", (72, 72), "black").save(image_path)
    artwork = tmp_path / "low-resolution.pdf"
    document = pymupdf.open()
    page = document.new_page(width=72, height=72)
    page.insert_image(pymupdf.Rect(0, 0, 72, 72), filename=image_path)
    document.save(artwork)
    document.close()
    spec = LabelSpec.from_dict(
        {"artwork": artwork.name, "width_mm": 25.4, "height_mm": 25.4, "min_dpi": 300}, tmp_path
    )

    report = validate(spec)

    assert not report.passed
    assert report.metadata["pdf"]["embedded_image_dpi"] == [72.0]
    assert any(issue.code == "PDF_IMAGE_DPI_TOO_LOW" for issue in report.issues)


def test_pdf_embedded_image_dpi_accepts_high_resolution_artwork(tmp_path):
    image_path = tmp_path / "source.png"
    Image.new("RGB", (600, 600), "black").save(image_path)
    artwork = tmp_path / "high-resolution.pdf"
    document = pymupdf.open()
    page = document.new_page(width=72, height=72)
    page.insert_image(pymupdf.Rect(0, 0, 72, 72), filename=image_path)
    document.save(artwork)
    document.close()
    spec = LabelSpec.from_dict(
        {"artwork": artwork.name, "width_mm": 25.4, "height_mm": 25.4, "min_dpi": 300}, tmp_path
    )

    report = validate(spec)

    assert report.passed
    assert report.metadata["pdf"]["embedded_image_dpi"] == [600.0]


def test_cli_malformed_pdf_fails_closed(tmp_path, capsys):
    artwork = tmp_path / "broken.pdf"
    artwork.write_bytes(b"not a PDF")
    config = tmp_path / "label.json"
    config.write_text(
        json.dumps({"artwork": artwork.name, "width_mm": 100, "height_mm": 50}),
        encoding="utf-8",
    )

    assert main(["validate", str(config), "--json"]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["passed"] is False
    assert report["issues"][0]["code"] == "PDF_INVALID"
