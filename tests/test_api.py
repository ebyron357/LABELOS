"""HTTP API authentication, validation, packaging, and security tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from labelos.api import create_app
from labelos.jobs import ProductionService
from labelos.storage import LocalStorage

ROOT = Path(__file__).parent.parent


@pytest.fixture()
def api_env(tmp_path, monkeypatch):
    token = "test-token-please-change"
    monkeypatch.setenv("LABELOS_API_TOKEN", token)
    monkeypatch.setenv("LABELOS_STORAGE_PATH", str(tmp_path / "storage"))
    storage = LocalStorage(tmp_path / "storage")
    storage.ensure_layout()
    service = ProductionService(storage)
    app = create_app(service)
    client = TestClient(app)
    return client, token, storage, service


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def passing_config() -> dict:
    return {
        "artwork": str(ROOT / "fixtures" / "passing-label.svg"),
        "width_mm": 100,
        "height_mm": 50,
        "bleed_mm": 3,
        "safe_area_mm": 2,
        "required_copy": ["Example Product", "NET 250 g"],
        "sku": "ALT-SYR-MANGO-001",
        "revision": "1.0",
    }


def test_health_is_public(api_env):
    client, _, _, _ = api_env
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["status"] == "ok"


def test_listen_port_prefers_platform_port(monkeypatch):
    from labelos.api import resolve_listen_port

    monkeypatch.setenv("PORT", "10000")
    monkeypatch.setenv("LABELOS_API_PORT", "8080")
    assert resolve_listen_port() == 10000
    monkeypatch.delenv("PORT")
    assert resolve_listen_port() == 8080


def test_doctor_requires_auth(api_env):
    client, token, _, _ = api_env
    assert client.get("/doctor").status_code == 401
    assert client.get("/doctor", headers={"Authorization": "Bearer wrong"}).status_code == 401
    response = client.get("/doctor", headers=auth(token))
    assert response.status_code == 200
    assert response.json()["success"] is True
    assert "tools" in response.json()["result"]


def test_validate_success(api_env):
    client, token, _, _ = api_env
    response = client.post("/validate", headers=auth(token), json={"config": passing_config()})
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["result"]["overall"] == "PASS"
    assert body["result"]["failed"] == []
    assert any(check["status"] in {"PASS", "WARN", "FAIL"} for check in body["result"]["checks"])


def test_validate_failure_missing_copy(api_env):
    client, token, _, _ = api_env
    config = passing_config()
    config["required_copy"] = ["ABSENT COPY"]
    response = client.post("/validate", headers=auth(token), json={"config": config})
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is False
    assert body["status"] == "REJECTED_VALIDATION"
    assert "REQUIRED_COPY_MISSING" in body["result"]["failed"]


def test_malformed_configuration(api_env):
    client, token, _, _ = api_env
    response = client.post(
        "/validate",
        headers=auth(token),
        json={"config": {"width_mm": 10}},
    )
    assert response.status_code == 400
    assert response.json()["result"]["error"]["code"] == "CONFIG_INVALID"


def test_path_traversal_rejected_on_package(api_env):
    client, token, _, _ = api_env
    response = client.post(
        "/package",
        headers=auth(token),
        json={
            "config": passing_config(),
            "destination": "../outside-release",
        },
    )
    assert response.status_code == 400
    assert response.json()["result"]["error"]["code"] == "PATH_TRAVERSAL"


def test_package_and_verify(api_env):
    client, token, _storage, _ = api_env
    response = client.post(
        "/package",
        headers=auth(token),
        json={"config": passing_config(), "destination": "adhoc/demo-release"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    package_path = body["result"]["package_path"]
    verify = client.post(
        "/verify-package",
        headers=auth(token),
        json={"destination": package_path},
    )
    assert verify.status_code == 200
    assert verify.json()["success"] is True


def test_corrupted_package_fails_verification(api_env):
    client, token, _, _ = api_env
    packaged = client.post(
        "/package",
        headers=auth(token),
        json={"config": passing_config(), "destination": "adhoc/corrupt-me"},
    ).json()
    package_path = Path(packaged["result"]["package_path"])
    artwork = next(package_path.glob("*.svg"))
    artwork.write_text("tampered", encoding="utf-8")
    verify = client.post(
        "/verify-package",
        headers=auth(token),
        json={"destination": str(package_path)},
    )
    assert verify.status_code == 200
    assert verify.json()["success"] is False
    assert verify.json()["status"] == "PACKAGE_VERIFICATION_FAILED"


def test_job_duplicate_skipped(api_env):
    client, token, _, _ = api_env
    payload = {
        "config": passing_config(),
        "product_data": {
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
            },
        },
        "auto_validate": True,
    }
    first = client.post("/jobs", headers=auth(token), json=payload)
    assert first.status_code == 200
    second = client.post("/jobs", headers=auth(token), json=payload)
    assert second.status_code == 200
    assert second.json()["status"] == "DUPLICATE_SKIPPED"


def test_job_package_verify_approve_release(api_env):
    client, token, _, service = api_env
    config = passing_config()
    create = client.post(
        "/jobs",
        headers=auth(token),
        json={
            "config": config,
            "product_data": {
                "product": {
                    "brand": "ALTERNATIVE",
                    "name": "Mango Syrup",
                    "sku": "ALT-SYR-MANGO-001",
                    "revision": "1.1",
                },
                "label": {
                    "template": "alternative-syrup.ai",
                    "width_mm": 100,
                    "height_mm": 50,
                    "bleed_mm": 3,
                },
                "copy": {"product_name": "Example Product", "net_weight": "NET 250 g"},
            },
            "auto_validate": True,
        },
    )
    assert create.status_code == 200
    job_id = create.json()["job_id"]
    assert create.json()["result"]["validation_result"]["overall"] == "PASS"

    packaged = client.post("/package", headers=auth(token), json={"job_id": job_id})
    assert packaged.status_code == 200
    verified = client.post("/verify-package", headers=auth(token), json={"job_id": job_id})
    assert verified.status_code == 200

    job = service.jobs.get(job_id)
    approve = client.post(
        f"/jobs/{job_id}/approve",
        headers=auth(token),
        json={
            "approver": "qa.operator",
            "comments": "Looks good",
            "approved": True,
            "artwork_checksum": job["package_artwork_checksum"],
        },
    )
    assert approve.status_code == 200
    assert approve.json()["status"] == "APPROVED_FOR_PRODUCTION"

    release = client.post(f"/jobs/{job_id}/release", headers=auth(token))
    assert release.status_code == 200
    assert release.json()["status"] == "RELEASED"

    report = client.get(f"/jobs/{job_id}/report", headers=auth(token))
    assert report.status_code == 200
    package = client.get(f"/jobs/{job_id}/package", headers=auth(token))
    assert package.status_code == 200


def test_approval_checksum_mismatch_rejected(api_env):
    client, token, _, _service = api_env
    config = passing_config()
    create = client.post(
        "/jobs",
        headers=auth(token),
        json={
            "config": config,
            "product_data": {
                "product": {
                    "brand": "ALTERNATIVE",
                    "name": "Mango Syrup",
                    "sku": "ALT-SYR-MANGO-002",
                    "revision": "1.0",
                },
                "label": {"template": "alternative-syrup.ai", "width_mm": 100, "height_mm": 50},
                "copy": {"product_name": "Example Product", "net_weight": "NET 250 g"},
            },
            "auto_validate": True,
        },
    )
    job_id = create.json()["job_id"]
    client.post("/package", headers=auth(token), json={"job_id": job_id})
    client.post("/verify-package", headers=auth(token), json={"job_id": job_id})
    bad = client.post(
        f"/jobs/{job_id}/approve",
        headers=auth(token),
        json={"approver": "qa", "approved": True, "artwork_checksum": "0" * 64},
    )
    assert bad.status_code == 400
    assert bad.json()["result"]["error"]["code"] == "APPROVAL_CHECKSUM_MISMATCH"
