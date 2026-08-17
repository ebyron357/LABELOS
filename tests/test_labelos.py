import json
from base64 import b64encode
from io import BytesIO
from pathlib import Path

import barcode
import pymupdf
import qrcode
from barcode.writer import ImageWriter
from PIL import Image, ImageDraw

from labelos.cli import main
from labelos.models import LabelSpec
from labelos.package import create_package, verify_package
from labelos.validate import MM_PER_POINT, validate

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


def test_safe_area_content_fails_for_svg_fixture():
    spec = LabelSpec.from_dict(
        {
            "artwork": "fixtures/safe-area-violation.svg",
            "width_mm": 100,
            "height_mm": 50,
            "bleed_mm": 3,
            "safe_area_mm": 2,
        },
        ROOT,
    )

    report = validate(spec)

    assert not report.passed
    assert any(issue.code == "SAFE_AREA_CONTENT" for issue in report.issues)
    assert report.metadata["safe_area"]["content_pixels"] > 0


def test_safe_area_content_fails_for_png(tmp_path):
    artwork = tmp_path / "unsafe.png"
    image = Image.new("RGB", (212, 112), "white")
    ImageDraw.Draw(image).rectangle((7, 40, 8, 70), fill="black")
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

    assert not report.passed
    assert any(issue.code == "SAFE_AREA_CONTENT" for issue in report.issues)


def test_safe_area_content_fails_for_pdf(tmp_path):
    artwork = tmp_path / "unsafe.pdf"
    document = pymupdf.open()
    page = document.new_page(width=106 / MM_PER_POINT, height=56 / MM_PER_POINT)
    page.draw_rect(pymupdf.Rect(3.5 / MM_PER_POINT, 20 / MM_PER_POINT, 4.5 / MM_PER_POINT, 30 / MM_PER_POINT))
    document.save(artwork)
    document.close()
    spec = LabelSpec.from_dict(
        {
            "artwork": artwork.name,
            "width_mm": 100,
            "height_mm": 50,
            "bleed_mm": 3,
            "safe_area_mm": 2,
        },
        tmp_path,
    )

    report = validate(spec)

    assert not report.passed
    assert any(issue.code == "SAFE_AREA_CONTENT" for issue in report.issues)


def test_package_contains_verified_manifest(tmp_path):
    spec = passing_spec()
    report = validate(spec)
    manifest = create_package(spec, report, tmp_path / "release")
    assert manifest.is_file()
    assert not verify_package(manifest.parent)
    (manifest.parent / "passing-label.svg").write_text("tampered", encoding="utf-8")
    assert verify_package(manifest.parent) == ["artwork checksum mismatch: passing-label.svg"]


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


def test_barcode_expected_value_is_decoded_from_pdf(tmp_path):
    value = "LABELOS-PDF-12345"
    barcode_path = Path(
        barcode.get("code128", value, writer=ImageWriter()).save(str(tmp_path / "barcode"))
    )
    artwork = tmp_path / "barcode.pdf"
    document = pymupdf.open()
    page = document.new_page(width=100 / (25.4 / 72), height=100 / (25.4 / 72))
    page.insert_image(pymupdf.Rect(25, 50, 250, 150), filename=barcode_path)
    document.save(artwork)
    document.close()
    spec = LabelSpec.from_dict(
        {"artwork": artwork.name, "width_mm": 100, "height_mm": 100, "barcode_value": value}, tmp_path
    )

    report = validate(spec)

    assert report.passed
    assert report.metadata["decoded_values"] == [value]
