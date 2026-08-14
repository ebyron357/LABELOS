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


def test_malformed_pdf_fails_with_structured_error_without_cascading_checks(tmp_path):
    artwork = tmp_path / "malformed.pdf"
    artwork.write_bytes(b"%PDF-1.7\nthis is not a PDF")
    spec = LabelSpec.from_dict(
        {
            "artwork": artwork.name,
            "width_mm": 100,
            "height_mm": 50,
            "required_copy": ["Product name"],
            "barcode_value": "LABELOS-12345",
        },
        tmp_path,
    )

    report = validate(spec)

    assert not report.passed
    assert [issue.code for issue in report.issues] == ["PDF_INVALID"]
    assert report.metadata["artwork_readable"] is False
    assert "required-copy" not in report.checks
    assert "code-decode" not in report.checks


def test_package_contains_verified_manifest(tmp_path):
    spec = passing_spec()
    report = validate(spec)
    manifest = create_package(spec, report, tmp_path / "release")
    assert manifest.is_file()
    assert not verify_package(manifest.parent)
    (manifest.parent / "passing-label.svg").write_text("tampered", encoding="utf-8")
    assert verify_package(manifest.parent) == [
        "artwork byte count mismatch: passing-label.svg",
        "artwork checksum mismatch: passing-label.svg",
    ]


def test_verify_package_rejects_unsafe_or_malformed_manifest_entries(tmp_path):
    spec = passing_spec()
    manifest_path = create_package(spec, validate(spec), tmp_path / "release")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    manifest["artwork"]["file"] = "../outside.svg"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    assert verify_package(manifest_path.parent) == ["artwork file path is unsafe"]

    manifest["artwork"]["file"] = "passing-label.svg"
    manifest["artwork"]["sha256"] = "not-a-checksum"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    assert verify_package(manifest_path.parent) == ["artwork checksum is missing or invalid"]


def test_verify_package_rejects_symbolic_link_artifacts(tmp_path):
    spec = passing_spec()
    manifest_path = create_package(spec, validate(spec), tmp_path / "release")
    artwork = manifest_path.parent / "passing-label.svg"
    external_artwork = tmp_path / "external.svg"
    external_artwork.write_text(artwork.read_text(encoding="utf-8"), encoding="utf-8")
    artwork.unlink()
    artwork.symlink_to(external_artwork)

    assert verify_package(manifest_path.parent) == [
        "artwork file must not be a symbolic link: passing-label.svg"
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
        {"artwork": artwork.name, "width_mm": 100, "height_mm": 100, "barcode_value": value}, tmp_path
    )

    report = validate(spec)

    assert report.passed
    assert report.metadata["decoded_values"] == [value]


def test_safe_area_accepts_uniform_full_bleed_background(tmp_path):
    artwork = tmp_path / "safe.png"
    image = Image.new("RGB", (1060, 560), "white")
    ImageDraw.Draw(image).rectangle((60, 60, 1000, 500), fill="black")
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
    assert report.metadata["safe_area"]["content_bounds_px"] == [60, 60, 1001, 501]


def test_safe_area_rejects_content_outside_allowed_bounds(tmp_path):
    artwork = tmp_path / "unsafe.png"
    image = Image.new("RGB", (1060, 560), "white")
    ImageDraw.Draw(image).rectangle((20, 60, 1000, 500), fill="black")
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
    assert "SAFE_AREA_CONTENT_OUTSIDE" in [issue.code for issue in report.issues]


def test_safe_area_rejects_out_of_bounds_svg_content(tmp_path):
    artwork = tmp_path / "unsafe.svg"
    artwork.write_text(
        """<svg xmlns="http://www.w3.org/2000/svg" width="106mm" height="56mm" viewBox="0 0 106 56">
  <rect width="106" height="56" fill="white"/>
  <rect x="1" y="6" width="100" height="44" fill="black"/>
</svg>
""",
        encoding="utf-8",
    )
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
    assert "SAFE_AREA_CONTENT_OUTSIDE" in [issue.code for issue in report.issues]
