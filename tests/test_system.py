from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pymupdf as fitz
import qrcode
from barcode import Code128
from barcode.writer import ImageWriter
from PIL import Image

from labelos.models import LabelSpec, SymbolExpectation
from labelos.package import create_package, export_pdf
from labelos.validator import validate_image, validate_pdf


def make_artwork(path: Path, dpi: int = 300) -> Path:
    image = Image.new("RGB", (591, 354), "white")
    barcode = (
        Code128("123456789012", writer=ImageWriter())
        .render(
            writer_options={
                "module_width": 0.28,
                "module_height": 14,
                "font_size": 0,
                "quiet_zone": 2,
            }
        )
        .convert("RGB")
    )
    barcode.thumbnail((300, 125))
    image.paste(barcode, (25, 25))
    qr = qrcode.make("https://example.com/label").convert("RGB")
    qr.thumbnail((150, 150))
    image.paste(qr, (400, 25))
    image.save(path, dpi=(dpi, dpi))
    return path


def spec() -> LabelSpec:
    return LabelSpec(
        width_mm=50,
        height_mm=30,
        minimum_dpi=300,
        barcode=SymbolExpectation("123456789012", "Code128"),
        qr=SymbolExpectation("https://example.com/label", "QRCode"),
        required_copy=("NET CONTENTS 12 OZ",),
    )


def test_image_validation_decodes_barcode_and_qr(tmp_path: Path) -> None:
    result = validate_image(make_artwork(tmp_path / "label.png"), spec())
    checks = {check.name: check.passed for check in result.checks}
    assert checks["dimensions"]
    assert checks["resolution"]
    assert checks["barcode"]
    assert checks["qr"]


def test_validation_rejects_wrong_symbol_and_low_resolution(tmp_path: Path) -> None:
    image = make_artwork(tmp_path / "label.png", dpi=72)
    wrong = LabelSpec(width_mm=50, height_mm=30, barcode=SymbolExpectation("wrong"))
    result = validate_image(image, wrong)
    assert not result.valid
    assert any(check.name == "resolution" and not check.passed for check in result.checks)
    assert any(check.name == "barcode" and not check.passed for check in result.checks)


def test_pdf_validation_and_delivery_package(tmp_path: Path) -> None:
    image = make_artwork(tmp_path / "label.png")
    pdf = export_pdf(image, spec(), tmp_path / "label.pdf")
    document = fitz.open(pdf)
    document[0].insert_text((10, 75), "NET CONTENTS 12 OZ", fontsize=8)
    document.save(tmp_path / "with-copy.pdf")
    document.close()
    pdf = tmp_path / "with-copy.pdf"
    result = validate_pdf(pdf, spec())
    assert result.valid, result.to_dict()
    manifest = create_package(pdf, spec(), tmp_path / "delivery")
    assert manifest["artwork"]["sha256"]
    assert json.loads((tmp_path / "delivery" / "validation-report.json").read_text())["valid"]


def test_cli_exit_codes_and_doctor(tmp_path: Path) -> None:
    image = make_artwork(tmp_path / "label.png")
    specification = tmp_path / "spec.json"
    specification.write_text(
        json.dumps(
            {
                "width_mm": 50,
                "height_mm": 30,
                "barcode": {"value": "123456789012", "format": "Code128"},
                "qr": {"value": "https://example.com/label", "format": "QRCode"},
            }
        )
    )
    doctor = subprocess.run(
        [sys.executable, "-m", "labelos.cli", "doctor"], capture_output=True, text=True, check=False
    )
    assert doctor.returncode == 0
    run = subprocess.run(
        [
            sys.executable,
            "-m",
            "labelos.cli",
            "validate-image",
            str(image),
            "--spec",
            str(specification),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert run.returncode == 0, run.stderr
    assert json.loads(run.stdout)["valid"]
