"""End-to-end acceptance sequence using the bundled production-like fixture label.

This proves: product data → (dry-run generation stand-in) → LABELOS validate →
package → verify → approval → release, then intentional defect gating.

A live Adobe Illustrator workstation + approved .ai template remains required for
non-dry-run artwork generation. That step is marked BLOCKED without Illustrator.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from illustrator_bridge.server import create_bridge_app
from labelos.api import create_app
from labelos.jobs import ProductionService
from labelos.storage import LocalStorage

ROOT = Path(__file__).parent.parent


@pytest.fixture()
def stack(tmp_path, monkeypatch):
    token = "e2e-token"
    monkeypatch.setenv("LABELOS_API_TOKEN", token)
    monkeypatch.setenv("LABELOS_BRIDGE_TOKEN", token)
    monkeypatch.setenv("LABELOS_STORAGE_PATH", str(tmp_path / "storage"))
    monkeypatch.setenv("LABELOS_TEMPLATES_PATH", str(tmp_path / "templates"))
    monkeypatch.setenv("LABELOS_BRIDGE_OUTPUT_PATH", str(tmp_path / "generated"))
    (tmp_path / "templates").mkdir()
    (tmp_path / "templates" / "alternative-syrup.ai").write_bytes(b"%AI-PLACEHOLDER")
    storage = LocalStorage(tmp_path / "storage")
    storage.ensure_layout()
    service = ProductionService(storage)
    api = TestClient(create_app(service))
    bridge = TestClient(create_bridge_app())
    return api, bridge, token, service, tmp_path


def product_data() -> dict:
    return json.loads((ROOT / "examples" / "product-mango-syrup.json").read_text(encoding="utf-8"))


def test_acceptance_happy_path_and_defect_gating(stack):
    api, bridge, token, service, tmp_path = stack
    headers = {"Authorization": f"Bearer {token}"}

    # 1) Product data validated by bridge dry-run generation
    generated = bridge.post(
        "/generate",
        headers=headers,
        json={
            "product_data": product_data(),
            "template_path": "alternative-syrup.ai",
            "dry_run": True,
        },
    )
    assert generated.status_code == 200
    artwork = Path(generated.json()["result"]["outputs"][0]["path"])
    assert artwork.is_file()

    # 2) LABELOS validation using generated artwork + product-derived config
    config = {
        "artwork": str(artwork),
        "width_mm": 100,
        "height_mm": 50,
        "bleed_mm": 3,
        "safe_area_mm": 2,
        "min_dpi": 300,
        "required_copy": ["Example Product", "NET 250 g"],
        "sku": "ALT-SYR-MANGO-001",
        "revision": "1.0",
    }
    validate = api.post("/validate", headers=headers, json={"config": config})
    assert validate.status_code == 200
    assert validate.json()["result"]["overall"] == "PASS"

    # 3) Job → package → verify → approve → release
    job = api.post(
        "/jobs",
        headers=headers,
        json={
            "config": config,
            "product_data": product_data(),
            "artwork_path": str(artwork),
            "auto_validate": True,
            "mode": "NORMAL",
            "operator": "acceptance-test",
        },
    )
    assert job.status_code == 200
    job_id = job.json()["job_id"]
    assert api.post("/package", headers=headers, json={"job_id": job_id}).json()["success"]
    assert api.post("/verify-package", headers=headers, json={"job_id": job_id}).json()["success"]
    stored = service.jobs.get(job_id)
    assert (
        api.post(
            f"/jobs/{job_id}/approve",
            headers=headers,
            json={
                "approver": "acceptance.approver",
                "comments": "E2E acceptance",
                "approved": True,
                "artwork_checksum": stored["artwork_checksum"],
            },
        ).json()["status"]
        == "APPROVED_FOR_PRODUCTION"
    )
    assert api.post(f"/jobs/{job_id}/release", headers=headers).json()["status"] == "RELEASED"

    # 4) Defect gating — each defect must prevent a clean PASS / release package path
    defects = {
        "DIMENSIONS_MISMATCH": {**config, "width_mm": 10, "height_mm": 10},
        "REQUIRED_COPY_MISSING": {**config, "required_copy": ["MISSING-COPY-XYZ"]},
    }
    for code, bad_config in defects.items():
        result = api.post("/validate", headers=headers, json={"config": bad_config}).json()
        assert result["success"] is False
        assert code in result["result"]["failed"]
        # Failed artwork must never package through job path after failed validation
        blocked = api.post(
            "/package",
            headers=headers,
            json={"config": bad_config, "destination": f"adhoc/should-fail-{code.lower()}"},
        ).json()
        assert blocked["success"] is False

    # Code / DPI defects on generated raster fixtures
    import barcode
    import qrcode
    from barcode.writer import ImageWriter
    from PIL import Image

    bad_qr = tmp_path / "bad-qr.png"
    qrcode.make("https://example.test/wrong").save(bad_qr)
    qr_cfg = {
        "artwork": str(bad_qr),
        "width_mm": 20,
        "height_mm": 20,
        "min_dpi": 1,
        "qr_value": "https://example.test/expected",
    }
    qr_result = api.post("/validate", headers=headers, json={"config": qr_cfg}).json()
    assert qr_result["success"] is False
    assert "CODE_VALUE_MISMATCH" in qr_result["result"]["failed"]

    bad_bc_path = Path(
        barcode.get("code128", "WRONG-CODE", writer=ImageWriter()).save(str(tmp_path / "bad-bc"))
    )
    bc_cfg = {
        "artwork": str(bad_bc_path),
        "width_mm": 100,
        "height_mm": 40,
        "min_dpi": 1,
        "barcode_value": "EXPECTED-CODE",
    }
    bc_result = api.post("/validate", headers=headers, json={"config": bc_cfg}).json()
    assert bc_result["success"] is False
    assert "CODE_VALUE_MISMATCH" in bc_result["result"]["failed"]

    low_dpi = tmp_path / "low-dpi.png"
    Image.new("RGB", (50, 25), color=(255, 255, 255)).save(low_dpi)
    dpi_cfg = {
        "artwork": str(low_dpi),
        "width_mm": 100,
        "height_mm": 50,
        "bleed_mm": 0,
        "min_dpi": 300,
        "required_copy": [],
    }
    dpi_result = api.post("/validate", headers=headers, json={"config": dpi_cfg}).json()
    assert dpi_result["success"] is False
    assert "DPI_TOO_LOW" in dpi_result["result"]["failed"]

    # Corrupted package fails verification
    ok_pkg = api.post(
        "/package",
        headers=headers,
        json={"config": config, "destination": "adhoc/to-corrupt"},
    ).json()
    package_dir = Path(ok_pkg["result"]["package_path"])
    next(iter(package_dir.glob("*.svg"))).write_text("corrupt", encoding="utf-8")

    verify = api.post(
        "/verify-package",
        headers=headers,
        json={"destination": str(package_dir)},
    ).json()
    assert verify["success"] is False
    assert verify["status"] == "PACKAGE_VERIFICATION_FAILED"
