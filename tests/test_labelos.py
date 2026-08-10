import hashlib
import json
from base64 import b64encode
from io import BytesIO
from pathlib import Path

import barcode
import pymupdf
import qrcode
from barcode.writer import ImageWriter

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


def test_package_contains_verified_manifest(tmp_path):
    spec = passing_spec()
    report = validate(spec)
    manifest = create_package(spec, report, tmp_path / "release")
    assert manifest.is_file()
    assert not verify_package(manifest.parent)
    package_spec = json.loads((manifest.parent / "label-spec.json").read_text(encoding="utf-8"))
    assert package_spec["schema_version"] == 1
    assert package_spec["artwork"] == "passing-label.svg"
    (manifest.parent / "passing-label.svg").write_text("tampered", encoding="utf-8")
    failures = verify_package(manifest.parent)
    assert "artwork checksum mismatch: passing-label.svg" in failures
    assert "artwork byte count mismatch: passing-label.svg" in failures


def test_package_verification_rejects_untrusted_manifest_entries(tmp_path):
    spec = passing_spec()
    manifest_path = create_package(spec, validate(spec), tmp_path / "release")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["artwork"]["file"] = "../outside.svg"
    manifest["label_spec"]["sha256"] = "NOT-A-DIGEST"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    failures = verify_package(manifest_path.parent)

    assert "artwork file must be a package-local filename" in failures
    assert "label_spec checksum is not a lowercase SHA-256 digest: label-spec.json" in failures


def test_package_verification_requires_passing_report(tmp_path):
    spec = passing_spec()
    manifest_path = create_package(spec, validate(spec), tmp_path / "release")
    report_path = manifest_path.parent / "validation-report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["passed"] = False
    report_path.write_text(json.dumps(report), encoding="utf-8")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["validation_report"]["sha256"] = hashlib.sha256(report_path.read_bytes()).hexdigest()
    manifest["validation_report"]["bytes"] = report_path.stat().st_size
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    assert "validation report does not record a passing validation" in verify_package(manifest_path.parent)


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


def test_invalid_pdf_reports_validation_error(tmp_path):
    artwork = tmp_path / "invalid.pdf"
    artwork.write_bytes(b"not a PDF")
    spec = LabelSpec.from_dict(
        {"artwork": artwork.name, "width_mm": 100, "height_mm": 50}, tmp_path
    )

    report = validate(spec)

    assert not report.passed
    assert report.issues[0].code == "PDF_INVALID"


def test_safe_area_passes_for_svg_content_inside_margin(tmp_path):
    artwork = tmp_path / "safe.svg"
    artwork.write_text(
        (
            '<svg xmlns="http://www.w3.org/2000/svg" width="106mm" height="56mm" '
            'viewBox="0 0 106 56"><rect width="106" height="56" fill="#fff"/>'
            '<text x="10" y="20">Safe copy</text></svg>'
        ),
        encoding="utf-8",
    )
    spec = LabelSpec.from_dict(
        {"artwork": artwork.name, "width_mm": 100, "height_mm": 50, "bleed_mm": 3, "safe_area_mm": 2},
        tmp_path,
    )

    report = validate(spec)

    assert report.passed
    assert "safe-area" in report.checks


def test_safe_area_rejects_svg_content_in_bleed(tmp_path):
    artwork = tmp_path / "unsafe.svg"
    artwork.write_text(
        (
            '<svg xmlns="http://www.w3.org/2000/svg" width="106mm" height="56mm" '
            'viewBox="0 0 106 56"><text x="1" y="20">Unsafe copy</text></svg>'
        ),
        encoding="utf-8",
    )
    spec = LabelSpec.from_dict(
        {"artwork": artwork.name, "width_mm": 100, "height_mm": 50, "bleed_mm": 3, "safe_area_mm": 2},
        tmp_path,
    )

    assert any(issue.code == "SAFE_AREA_VIOLATION" for issue in validate(spec).issues)


def test_safe_area_rejects_pdf_content_in_bleed(tmp_path):
    artwork = tmp_path / "unsafe.pdf"
    document = pymupdf.open()
    page = document.new_page(width=106 / (25.4 / 72), height=56 / (25.4 / 72))
    page.insert_text((3 / (25.4 / 72), 20 / (25.4 / 72)), "Unsafe copy")
    document.save(artwork)
    document.close()
    spec = LabelSpec.from_dict(
        {"artwork": artwork.name, "width_mm": 100, "height_mm": 50, "bleed_mm": 3, "safe_area_mm": 2},
        tmp_path,
    )

    assert any(issue.code == "SAFE_AREA_VIOLATION" for issue in validate(spec).issues)


def test_example_safe_area_is_enforced():
    spec = LabelSpec.from_dict(json.loads((ROOT / "examples/label.json").read_text(encoding="utf-8")), ROOT / "examples")

    report = validate(spec)

    assert report.passed
    assert "safe-area" in report.checks


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
