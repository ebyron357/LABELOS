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


def create_validated_job(
    client: TestClient, token: str, *, sku: str = "ALT-SYR-MANGO-001", config: dict | None = None
) -> str:
    response = client.post(
        "/jobs",
        headers=auth(token),
        json={
            "config": config or passing_config(),
            "product_data": {
                "product": {
                    "brand": "ALTERNATIVE",
                    "name": "Mango Syrup",
                    "sku": sku,
                    "revision": "1.0",
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
    assert response.status_code == 200
    return response.json()["job_id"]


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
            "artwork_checksum": job["artwork_checksum"],
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


def test_approval_requires_successful_package_verification(api_env):
    client, token, _, service = api_env
    job_id = create_validated_job(client, token)
    assert client.post("/package", headers=auth(token), json={"job_id": job_id}).status_code == 200
    job = service.jobs.get(job_id)

    approval = client.post(
        f"/jobs/{job_id}/approve",
        headers=auth(token),
        json={"approver": "qa", "approved": True, "artwork_checksum": job["package_artwork_checksum"]},
    )

    assert approval.status_code == 400
    assert approval.json()["result"]["error"]["code"] == "APPROVAL_STATE"


def test_release_requires_successful_current_verification(api_env):
    client, token, _, service = api_env
    job_id = create_validated_job(client, token)
    assert client.post("/package", headers=auth(token), json={"job_id": job_id}).status_code == 200
    job = service.jobs.get(job_id)
    # Simulate a legacy state created by the previously permitted direct approval path.
    job["status"] = "APPROVED_FOR_PRODUCTION"
    job["approval_result"] = {"approved": True, "artwork_checksum": job["package_artwork_checksum"]}
    service.jobs.save(job)

    release = client.post(f"/jobs/{job_id}/release", headers=auth(token))

    assert release.status_code == 400
    assert release.json()["result"]["error"]["code"] == "RELEASE_VERIFICATION_REQUIRED"


def test_release_rejects_tampered_package_after_verification(api_env):
    client, token, _, service = api_env
    job_id = create_validated_job(client, token)
    assert client.post("/package", headers=auth(token), json={"job_id": job_id}).status_code == 200
    assert client.post("/verify-package", headers=auth(token), json={"job_id": job_id}).status_code == 200
    job = service.jobs.get(job_id)
    packaged_artwork = next(Path(job["package_path"]).glob("*.svg"))
    packaged_artwork.write_text("tampered", encoding="utf-8")
    assert client.post(
        f"/jobs/{job_id}/approve",
        headers=auth(token),
        json={"approver": "qa", "approved": True, "artwork_checksum": job["package_artwork_checksum"]},
    ).status_code == 200

    release = client.post(f"/jobs/{job_id}/release", headers=auth(token))

    assert release.status_code == 400
    assert release.json()["result"]["error"]["code"] == "RELEASE_VERIFICATION_REQUIRED"


def test_failed_job_verification_is_persisted_as_failed(api_env):
    client, token, _, service = api_env
    job_id = create_validated_job(client, token)
    assert client.post("/package", headers=auth(token), json={"job_id": job_id}).status_code == 200
    job = service.jobs.get(job_id)
    next(Path(job["package_path"]).glob("*.svg")).write_text("tampered", encoding="utf-8")

    verification = client.post("/verify-package", headers=auth(token), json={"job_id": job_id})

    assert verification.status_code == 400
    job = service.jobs.get(job_id)
    assert job["status"] == "PACKAGE_VERIFICATION_FAILED"
    assert job["package_verification"] == {"passed": False}


def test_release_rejects_stale_verification_identity(api_env):
    client, token, _, service = api_env
    job_id = create_validated_job(client, token)
    assert client.post("/package", headers=auth(token), json={"job_id": job_id}).status_code == 200
    assert client.post("/verify-package", headers=auth(token), json={"job_id": job_id}).status_code == 200
    job = service.jobs.get(job_id)
    job["package_verification"]["manifest_checksum"] = "0" * 64
    service.jobs.save(job)
    assert client.post(
        f"/jobs/{job_id}/approve",
        headers=auth(token),
        json={"approver": "qa", "approved": True, "artwork_checksum": job["package_artwork_checksum"]},
    ).status_code == 200

    release = client.post(f"/jobs/{job_id}/release", headers=auth(token))

    assert release.status_code == 400
    assert release.json()["result"]["error"]["code"] == "RELEASE_VERIFICATION_STALE"


def test_approval_requires_exact_current_packaged_artwork_checksum(api_env):
    client, token, _, service = api_env
    job_id = create_validated_job(client, token)
    assert client.post("/package", headers=auth(token), json={"job_id": job_id}).status_code == 200
    assert client.post("/verify-package", headers=auth(token), json={"job_id": job_id}).status_code == 200
    job = service.jobs.get(job_id)

    missing = client.post(
        f"/jobs/{job_id}/approve",
        headers=auth(token),
        json={"approver": "qa", "approved": True},
    )
    assert missing.status_code == 400
    assert missing.json()["result"]["error"]["code"] == "APPROVAL_CHECKSUM_REQUIRED"

    stale = client.post(
        f"/jobs/{job_id}/approve",
        headers=auth(token),
        json={"approver": "qa", "approved": True, "artwork_checksum": "0" * 64},
    )
    assert stale.status_code == 400
    assert stale.json()["result"]["error"]["code"] == "APPROVAL_CHECKSUM_MISMATCH"

    exact = client.post(
        f"/jobs/{job_id}/approve",
        headers=auth(token),
        json={"approver": "qa", "approved": True, "artwork_checksum": job["package_artwork_checksum"]},
    )
    assert exact.status_code == 200


def test_approval_uses_artwork_bytes_packaged_after_source_changes(api_env, tmp_path):
    client, token, _, service = api_env
    artwork = tmp_path / "label.svg"
    artwork.write_bytes((ROOT / "fixtures" / "passing-label.svg").read_bytes())
    config = passing_config()
    config["artwork"] = str(artwork)
    job_id = create_validated_job(client, token, config=config)
    source_checksum = service.jobs.get(job_id)["artwork_checksum"]
    artwork.write_text(artwork.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    assert client.post("/package", headers=auth(token), json={"job_id": job_id}).status_code == 200
    assert client.post("/verify-package", headers=auth(token), json={"job_id": job_id}).status_code == 200
    job = service.jobs.get(job_id)
    assert job["package_artwork_checksum"] != source_checksum

    stale = client.post(
        f"/jobs/{job_id}/approve",
        headers=auth(token),
        json={"approver": "qa", "approved": True, "artwork_checksum": source_checksum},
    )
    assert stale.status_code == 400
    assert stale.json()["result"]["error"]["code"] == "APPROVAL_CHECKSUM_MISMATCH"

    exact = client.post(
        f"/jobs/{job_id}/approve",
        headers=auth(token),
        json={"approver": "qa", "approved": True, "artwork_checksum": job["package_artwork_checksum"]},
    )
    assert exact.status_code == 200


def test_repackaging_invalidates_verification_and_approval(api_env, monkeypatch, tmp_path):
    client, token, storage, service = api_env
    destinations = iter((tmp_path / "first-package", tmp_path / "second-package"))
    monkeypatch.setattr(storage, "release_dir", lambda *_args: next(destinations))
    job_id = create_validated_job(client, token)
    assert client.post("/package", headers=auth(token), json={"job_id": job_id}).status_code == 200
    assert client.post("/verify-package", headers=auth(token), json={"job_id": job_id}).status_code == 200
    first = service.jobs.get(job_id)
    assert client.post(
        f"/jobs/{job_id}/approve",
        headers=auth(token),
        json={"approver": "qa", "approved": True, "artwork_checksum": first["package_artwork_checksum"]},
    ).status_code == 200

    repackaged = client.post("/package", headers=auth(token), json={"job_id": job_id})

    assert repackaged.status_code == 200
    job = service.jobs.get(job_id)
    assert job["status"] == "TECHNICALLY_VALIDATED"
    assert job["package_verification"] is None
    assert job["approval_result"] is None
    assert job["timestamps"]["verified_at"] is None
    assert job["timestamps"]["approval_at"] is None
