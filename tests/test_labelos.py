import hashlib
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
from labelos.validate import validate

ROOT = Path(__file__).parent.parent


def passing_spec() -> LabelSpec:
    return LabelSpec.from_dict(
        {
            "artwork": "fixtures/passing-label.svg",
            "width_mm": 100,
            "height_mm": 50,
            "bleed_mm": 3,
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


def test_png_safe_area_accepts_artwork_on_boundary(tmp_path):
    artwork = tmp_path / "boundary.png"
    image = Image.new("RGBA", (106, 56), "white")
    ImageDraw.Draw(image).rectangle((5, 5, 14, 14), fill="black")
    image.save(artwork)
    spec = LabelSpec.from_dict(
        {"artwork": artwork.name, "width_mm": 100, "height_mm": 50, "bleed_mm": 3, "safe_area_mm": 2, "min_dpi": 1},
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
        {"artwork": artwork.name, "width_mm": 100, "height_mm": 50, "bleed_mm": 3, "safe_area_mm": 2, "min_dpi": 1},
        tmp_path,
    )

    assert any(issue.code == "SAFE_AREA_VIOLATION" for issue in validate(spec).issues)


def test_png_safe_area_ignores_fully_transparent_pixels(tmp_path):
    artwork = tmp_path / "transparent.png"
    image = Image.new("RGBA", (106, 56), (255, 255, 255, 255))
    image.putpixel((0, 0), (0, 0, 0, 0))
    image.save(artwork)
    spec = LabelSpec.from_dict(
        {"artwork": artwork.name, "width_mm": 100, "height_mm": 50, "bleed_mm": 3, "safe_area_mm": 2, "min_dpi": 1},
        tmp_path,
    )

    assert validate(spec).passed


def test_svg_safe_area_rejects_negative_coordinates(tmp_path):
    artwork = tmp_path / "negative.svg"
    artwork.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="106mm" height="56mm" viewBox="0 0 106 56">'
        '<rect x="-1" y="10" width="10" height="10" fill="black"/></svg>',
        encoding="utf-8",
    )
    spec = LabelSpec.from_dict(
        {"artwork": artwork.name, "width_mm": 100, "height_mm": 50, "bleed_mm": 3, "safe_area_mm": 2},
        tmp_path,
    )

    assert {issue.code for issue in validate(spec).issues} == {"SAFE_AREA_VIOLATION"}


def test_svg_safe_area_rejects_transformed_artwork(tmp_path):
    artwork = tmp_path / "transformed.svg"
    artwork.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="106mm" height="56mm" viewBox="0 0 106 56">'
        '<g transform="translate(98 0)"><rect x="0" y="10" width="10" height="10" fill="black"/></g></svg>',
        encoding="utf-8",
    )
    spec = LabelSpec.from_dict(
        {"artwork": artwork.name, "width_mm": 100, "height_mm": 50, "bleed_mm": 3, "safe_area_mm": 2},
        tmp_path,
    )

    assert {issue.code for issue in validate(spec).issues} == {"SAFE_AREA_VIOLATION"}


def test_svg_safe_area_rejects_text_extending_beyond_anchor(tmp_path):
    artwork = tmp_path / "text.svg"
    artwork.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="106mm" height="56mm" viewBox="0 0 106 56">'
        '<text x="100" y="30" font-size="12">HELLO</text></svg>',
        encoding="utf-8",
    )
    spec = LabelSpec.from_dict(
        {"artwork": artwork.name, "width_mm": 100, "height_mm": 50, "bleed_mm": 3, "safe_area_mm": 2},
        tmp_path,
    )

    assert {issue.code for issue in validate(spec).issues} == {"SAFE_AREA_VIOLATION"}


def test_malformed_svg_fails_structured(tmp_path):
    artwork = tmp_path / "broken.svg"
    artwork.write_text("<svg><g></svg>", encoding="utf-8")
    spec = LabelSpec.from_dict(
        {"artwork": artwork.name, "width_mm": 100, "height_mm": 50, "safe_area_mm": 2},
        tmp_path,
    )

    assert any(issue.code == "SVG_INVALID" for issue in validate(spec).issues)


def test_malformed_pdf_fails_structured(tmp_path):
    artwork = tmp_path / "broken.pdf"
    artwork.write_bytes(b"not a pdf")
    spec = LabelSpec.from_dict(
        {"artwork": artwork.name, "width_mm": 100, "height_mm": 50, "safe_area_mm": 2},
        tmp_path,
    )

    assert any(issue.code == "PDF_INVALID" for issue in validate(spec).issues)


def test_rotated_pdf_safe_area_validates_centered_content(tmp_path):
    artwork = tmp_path / "rotated.pdf"
    document = pymupdf.open()
    page = document.new_page(width=106 / (25.4 / 72), height=56 / (25.4 / 72))
    page.draw_rect(pymupdf.Rect(35, 15, 70, 40), color=(0, 0, 0), fill=(0, 0, 0))
    page.set_rotation(90)
    document.save(artwork)
    document.close()
    spec = LabelSpec.from_dict(
        {"artwork": artwork.name, "width_mm": 50, "height_mm": 100, "bleed_mm": 3, "safe_area_mm": 2},
        tmp_path,
    )

    assert validate(spec).passed


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


def test_verify_package_rejects_path_traversal(tmp_path):
    manifest = create_package(passing_spec(), validate(passing_spec()), tmp_path / "release")
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["artwork"]["file"] = "../outside.svg"
    manifest.write_text(json.dumps(data), encoding="utf-8")

    assert verify_package(manifest.parent) == ["artwork file path is invalid"]


def test_verify_package_rejects_symlink_entries(tmp_path):
    manifest = create_package(passing_spec(), validate(passing_spec()), tmp_path / "release")
    artwork_path = manifest.parent / "passing-label.svg"
    target = tmp_path / "outside.svg"
    target.write_text("outside", encoding="utf-8")
    artwork_path.unlink()
    artwork_path.symlink_to(target)

    assert verify_package(manifest.parent) == ["artwork file is missing or is not a regular file: passing-label.svg"]


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
