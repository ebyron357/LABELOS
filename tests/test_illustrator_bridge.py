"""Illustrator bridge request validation and dry-run generation tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from illustrator_bridge.server import create_bridge_app


@pytest.fixture()
def bridge(tmp_path, monkeypatch):
    token = "bridge-token"
    monkeypatch.setenv("LABELOS_BRIDGE_TOKEN", token)
    monkeypatch.setenv("LABELOS_TEMPLATES_PATH", str(tmp_path / "templates"))
    monkeypatch.setenv("LABELOS_BRIDGE_OUTPUT_PATH", str(tmp_path / "generated"))
    (tmp_path / "templates").mkdir()
    # Placeholder template marker file for path resolution tests.
    (tmp_path / "templates" / "alternative-syrup.ai").write_bytes(b"%PDF-PLACEHOLDER")
    client = TestClient(create_bridge_app())
    return client, token


def product_payload() -> dict:
    return {
        "product": {
            "brand": "ALTERNATIVE",
            "name": "Mango Syrup",
            "sku": "ALT-SYR-MANGO-001",
            "revision": "1.0",
        },
        "label": {
            "template": "alternative-syrup.ai",
            "width_mm": 100,
            "height_mm": 50,
            "bleed_mm": 3,
            "safe_area_mm": 2,
            "min_dpi": 300,
        },
        "copy": {
            "product_name": "Example Product",
            "net_weight": "NET 250 g",
            "ingredients": "Mango, Sugar, Water",
            "legal_copy": ["For food use only"],
        },
        "codes": {
            "barcode": "0123456789012",
            "qr": "https://example.com/product",
        },
        "printer": {"profile": None},
    }


def test_bridge_health(bridge):
    client, _ = bridge
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["success"] is True


def test_bridge_requires_auth(bridge):
    client, token = bridge
    assert client.get("/doctor").status_code == 401
    assert client.get("/doctor", headers={"Authorization": f"Bearer {token}"}).status_code == 200


def test_bridge_rejects_malformed_product_data(bridge):
    client, token = bridge
    response = client.post(
        "/generate",
        headers={"Authorization": f"Bearer {token}"},
        json={"product_data": {"product": {"sku": "bad"}}, "template_path": "alternative-syrup.ai"},
    )
    assert response.status_code == 400
    assert response.json()["result"]["error"]["code"] == "PRODUCT_SCHEMA_INVALID"


def test_bridge_dry_run_generates_standin(bridge, tmp_path):
    client, token = bridge
    response = client.post(
        "/generate",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "product_data": product_payload(),
            "template_path": "alternative-syrup.ai",
            "dry_run": True,
            "export_formats": ["pdf"],
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ARTWORK_GENERATED_DRY_RUN"
    outputs = body["result"]["outputs"]
    assert outputs
    assert Path(outputs[0]["path"]).is_file()


def test_bridge_live_generate_fails_closed_without_illustrator(bridge):
    client, token = bridge
    response = client.post(
        "/generate",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "product_data": product_payload(),
            "template_path": "alternative-syrup.ai",
            "dry_run": False,
        },
    )
    # Without Illustrator COM, generation must fail closed (not fake success).
    assert response.status_code == 503
    payload = response.json()
    assert payload["success"] is False
    assert payload["result"]["error"]["category"] == "ILLUSTRATOR_ERROR"
