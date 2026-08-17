import json
from base64 import b64encode
from hashlib import sha256
from io import BytesIO
from pathlib import Path

import barcode
import pymupdf
import qrcode
from barcode.writer import ImageWriter

from labelos.cli import main
from labelos.models import LabelSpec, Report
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
    (manifest.parent / "passing-label.svg").write_text("tampered", encoding="utf-8")
    assert verify_package(manifest.parent) == [
        "artwork byte count mismatch: passing-label.svg",
        "artwork checksum mismatch: passing-label.svg",
    ]


def test_package_manifest_includes_complete_report_integrity_metadata(tmp_path):
    manifest_path = create_package(passing_spec(), validate(passing_spec()), tmp_path / "release")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest["schema_version"] == 1
    assert manifest["validation_report"] == {
        "bytes": (manifest_path.parent / "validation-report.json").stat().st_size,
        "file": "validation-report.json",
        "passed": True,
        "sha256": _digest(manifest_path.parent / "validation-report.json"),
    }


def test_package_rejects_reserved_artwork_filenames(tmp_path):
    artwork = tmp_path / "manifest.json"
    artwork.write_text('<svg width="10mm" height="10mm"/>', encoding="utf-8")
    spec = LabelSpec.from_dict({"artwork": artwork.name, "width_mm": 10, "height_mm": 10}, tmp_path)

    try:
        create_package(spec, Report(source=str(artwork)), tmp_path / "release")
    except ValueError as error:
        assert "reserved" in str(error)
    else:
        raise AssertionError("Expected reserved artwork filename to be rejected")


def test_verify_package_rejects_manifest_path_traversal_and_unexpected_files(tmp_path):
    manifest_path = create_package(passing_spec(), validate(passing_spec()), tmp_path / "release")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["artwork"]["file"] = "../outside.svg"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    failures = verify_package(manifest_path.parent)

    assert "artwork manifest file is not an allowed package filename" in failures
    (manifest_path.parent / "unreviewed.txt").write_text("extra", encoding="utf-8")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["artwork"]["file"] = "passing-label.svg"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    assert verify_package(manifest_path.parent) == ["package contains unexpected files: unreviewed.txt"]


def test_verify_package_rejects_symlinks_and_inconsistent_validation_report(tmp_path):
    manifest_path = create_package(passing_spec(), validate(passing_spec()), tmp_path / "release")
    package = manifest_path.parent
    artwork = package / "passing-label.svg"
    artwork.unlink()
    artwork.symlink_to(ROOT / "fixtures/passing-label.svg")
    assert verify_package(package) == ["artwork file is missing or not a regular file: passing-label.svg"]

    artwork.unlink()
    artwork.write_bytes((ROOT / "fixtures/passing-label.svg").read_bytes())
    report_path = package / "validation-report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["metadata"]["spec"]["width_mm"] = 999
    report_path.write_text(json.dumps(report), encoding="utf-8")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["validation_report"]["bytes"] = report_path.stat().st_size
    manifest["validation_report"]["sha256"] = _digest(report_path)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    assert verify_package(package) == ["validation_report spec does not match manifest spec"]


def test_verify_package_rejects_malformed_manifest_and_cli_returns_failure(tmp_path, capsys):
    manifest_path = create_package(passing_spec(), validate(passing_spec()), tmp_path / "release")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["schema_version"] = 2
    manifest["validation_report"]["passed"] = False
    manifest["extra"] = "unverified"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    failures = verify_package(manifest_path.parent)

    assert "manifest.json has unsupported fields: extra" in failures
    assert "manifest.json has unsupported schema version" in failures
    assert "validation_report manifest must record a passing validation" in failures
    assert main(["verify-package", str(manifest_path.parent), "--json"]) == 1
    assert not json.loads(capsys.readouterr().out)["passed"]


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


def _digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()
