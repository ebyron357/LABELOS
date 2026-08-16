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


def _safe_area_spec(artwork: Path, root: Path) -> LabelSpec:
    return LabelSpec.from_dict(
        {
            "artwork": artwork.name,
            "width_mm": 10,
            "height_mm": 10,
            "bleed_mm": 1,
            "safe_area_mm": 1,
            "min_dpi": 300,
        },
        root,
    )


def test_svg_safe_area_allows_uniform_bleed_background(tmp_path):
    artwork = tmp_path / "safe.svg"
    artwork.write_text(
        """<svg xmlns="http://www.w3.org/2000/svg" width="12mm" height="12mm" viewBox="0 0 12 12">
<rect width="12" height="12" fill="white"/><rect x="2.1" y="2.1" width="7.8" height="7.8" fill="black"/>
</svg>""",
        encoding="utf-8",
    )

    report = validate(_safe_area_spec(artwork, tmp_path))

    assert report.passed
    assert "safe-area" in report.checks


def test_png_safe_area_flags_content_in_protected_margin(tmp_path):
    artwork = tmp_path / "unsafe.png"
    image = Image.new("RGB", (144, 144), "white")
    ImageDraw.Draw(image).rectangle((5, 60, 80, 80), fill="black")
    image.save(artwork, dpi=(304.8, 304.8))

    report = validate(_safe_area_spec(artwork, tmp_path))

    assert not report.passed
    assert "SAFE_AREA_VIOLATION" in [issue.code for issue in report.issues]


def test_pdf_safe_area_flags_content_in_protected_margin(tmp_path):
    artwork = tmp_path / "unsafe.pdf"
    document = pymupdf.open()
    page = document.new_page(width=12 / (25.4 / 72), height=12 / (25.4 / 72))
    page.draw_rect(page.rect, color=None, fill=(1, 1, 1))
    page.draw_rect(pymupdf.Rect(5, 20, 30, 35), color=None, fill=(0, 0, 0))
    document.save(artwork)
    document.close()

    report = validate(_safe_area_spec(artwork, tmp_path))

    assert not report.passed
    assert "SAFE_AREA_VIOLATION" in [issue.code for issue in report.issues]


def test_package_contains_verified_manifest(tmp_path):
    spec = passing_spec()
    report = validate(spec)
    manifest = create_package(spec, report, tmp_path / "release")
    assert manifest.is_file()
    assert not verify_package(manifest.parent)
    (manifest.parent / "passing-label.svg").write_text("tampered", encoding="utf-8")
    assert verify_package(manifest.parent) == [
        "artwork checksum mismatch: passing-label.svg",
        "artwork byte count mismatch: passing-label.svg",
    ]


def test_package_rejects_manifest_path_traversal_and_unexpected_files(tmp_path):
    manifest_path = create_package(passing_spec(), validate(passing_spec()), tmp_path / "release")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["artwork"]["file"] = "../outside.svg"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    (manifest_path.parent / "notes.txt").write_text("unexpected", encoding="utf-8")

    failures = verify_package(manifest_path.parent)

    assert "artwork file path is unsafe" in failures
    assert "unexpected package files: notes.txt, passing-label.svg" in failures


def test_package_rejects_dot_segments_and_path_separators(tmp_path):
    for index, name in enumerate((".", "..", "nested/file.svg", r"nested\file.svg")):
        destination = tmp_path / f"release-{index}"
        manifest_path = create_package(passing_spec(), validate(passing_spec()), destination)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["artwork"]["file"] = name
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        assert "artwork file path is unsafe" in verify_package(manifest_path.parent)


def test_package_rejects_manifest_byte_count_tampering(tmp_path):
    manifest_path = create_package(passing_spec(), validate(passing_spec()), tmp_path / "release")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["validation_report"]["bytes"] -= 1
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    assert verify_package(manifest_path.parent) == [
        "validation_report byte count mismatch: validation-report.json"
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
