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


NATIVE_LAYERS = [
    "DIELINE",
    "BLEED",
    "SAFE_AREA",
    "BACKGROUND",
    "BRAND",
    "COPY",
    "REGULATORY",
    "BARCODE",
    "QR",
    "VARNISH",
]


def write_native_evidence(tmp_path: Path, **overrides) -> dict:
    directory = tmp_path / "evidence"
    directory.mkdir(exist_ok=True)
    payload = {
        "missing_layers": [],
        "layers": list(NATIVE_LAYERS),
        "objects": ["BT-1000-30ML_QR", "BT-1000-30ML_BARCODE"],
        "reopened_without_repair": True,
    }
    payload.update(overrides.pop("payload", {}))
    (directory / "evidence.json").write_text(json.dumps(payload), encoding="utf-8")
    (directory / "build.log").write_text(overrides.pop("log", "build started\nPASSED\n"), encoding="utf-8")
    (directory / "preview.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)
    (directory / "master.ai").write_bytes(b"%PDF-1.5 native placeholder")
    return {
        "evidence_json": str(directory / "evidence.json"),
        "log": str(directory / "build.log"),
        "preview_png": str(directory / "preview.png"),
        "native_artwork": str(directory / "master.ai"),
        "required_layers": NATIVE_LAYERS,
        "required_objects": ["BT-1000-30ML_QR", "BT-1000-30ML_BARCODE"],
    }


def spec_with_evidence(tmp_path: Path, **overrides) -> LabelSpec:
    return LabelSpec.from_dict(
        {
            "artwork": str(ROOT / "fixtures/passing-label.svg"),
            "width_mm": 100,
            "height_mm": 50,
            "bleed_mm": 3,
            "native_evidence": write_native_evidence(tmp_path, **overrides),
        },
        tmp_path,
    )


def test_native_evidence_gate_passes(tmp_path):
    report = validate(spec_with_evidence(tmp_path))
    assert report.passed
    assert "native-build-evidence" in report.checks
    assert report.metadata["native_evidence"]["missing_layers"] == []
    assert report.metadata["native_evidence"]["blocked"] == [
        "printer_profile",
        "icc_profile",
        "regulatory_approval",
        "production_pdf",
    ]


def test_native_evidence_reports_missing_layers(tmp_path):
    report = validate(spec_with_evidence(tmp_path, payload={"missing_layers": ["VARNISH"]}))
    assert not report.passed
    assert any(issue.code == "NATIVE_LAYERS_MISSING" for issue in report.issues)


def test_native_evidence_requires_all_ten_layers(tmp_path):
    report = validate(spec_with_evidence(tmp_path, payload={"layers": NATIVE_LAYERS[:9]}))
    assert any(
        issue.code == "NATIVE_LAYERS_MISSING" and "VARNISH" in issue.message
        for issue in report.issues
    )


def test_native_evidence_requires_named_objects(tmp_path):
    report = validate(spec_with_evidence(tmp_path, payload={"objects": []}))
    assert any(issue.code == "NAMED_OBJECTS_MISSING" for issue in report.issues)


def test_native_evidence_requires_repair_free_reopen(tmp_path):
    report = validate(spec_with_evidence(tmp_path, payload={"reopened_without_repair": False}))
    assert any(issue.code == "NATIVE_REOPEN_UNPROVEN" for issue in report.issues)


def test_native_evidence_requires_log_to_end_with_passed(tmp_path):
    report = validate(spec_with_evidence(tmp_path, log="build started\nFAILED\n"))
    assert any(issue.code == "EVIDENCE_LOG_NOT_PASSED" for issue in report.issues)


def test_native_evidence_requires_every_artifact(tmp_path):
    spec = spec_with_evidence(tmp_path)
    spec.native_evidence.preview_png.unlink()
    report = validate(spec)
    assert any(issue.code == "EVIDENCE_ARTIFACT_MISSING" for issue in report.issues)


def test_package_records_and_verifies_native_evidence(tmp_path):
    spec = spec_with_evidence(tmp_path)
    manifest_path = create_package(spec, validate(spec), tmp_path / "release")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert set(manifest["native_evidence"]) == {
        "evidence_json",
        "log",
        "preview_png",
        "native_artwork",
    }
    assert manifest["blocked_requirements"] == [
        "printer_profile",
        "icc_profile",
        "regulatory_approval",
        "production_pdf",
    ]
    assert not verify_package(manifest_path.parent)
    (manifest_path.parent / "native-evidence" / "master.ai").write_bytes(b"tampered")
    assert verify_package(manifest_path.parent) == [
        "native evidence native_artwork checksum mismatch: master.ai"
    ]
