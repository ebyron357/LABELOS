"""Regression tests for release-gate and Illustrator export integrity."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from illustrator_bridge.server import create_bridge_app
from labelos.errors import LabelosException
from labelos.jobs import ProductionService
from labelos.schemas.lifecycle import JobLifecycle
from labelos.storage import LocalStorage

ROOT = Path(__file__).parent.parent


def _config() -> dict:
    return {
        "artwork": str(ROOT / "fixtures" / "passing-label.svg"),
        "width_mm": 100,
        "height_mm": 50,
        "bleed_mm": 3,
        "safe_area_mm": 2,
        "required_copy": ["Example Product", "NET 250 g"],
    }


def _product(sku: str) -> dict:
    return {
        "product": {"brand": "ALTERNATIVE", "name": "Mango Syrup", "sku": sku, "revision": "1.0"},
        "label": {"template": "alternative-syrup.ai", "width_mm": 100, "height_mm": 50},
        "copy": {"product_name": "Example Product", "net_weight": "NET 250 g"},
    }


def _validated_job(service: ProductionService, sku: str) -> str:
    job = service.create_or_get_job(product_data=_product(sku), config=_config())
    service.run_validate_job(job["job_id"])
    return job["job_id"]


def _approved_job(service: ProductionService, sku: str) -> str:
    job_id = _validated_job(service, sku)
    service.package_job(job_id)
    service.verify_job_package(job_id)
    job = service.jobs.get(job_id)
    service.approve(job_id, approver="qa", artwork_checksum=job["package_artwork_checksum"])
    return job_id


def test_approval_requires_successful_package_verification(tmp_path):
    service = ProductionService(LocalStorage(tmp_path / "storage"))
    job_id = _validated_job(service, "SKU-VERIFY-GATE")
    service.package_job(job_id)

    with pytest.raises(LabelosException) as error:
        service.approve(job_id, approver="qa")

    assert error.value.error.code == "APPROVAL_STATE"


def test_verification_binds_current_manifest_checksum(tmp_path):
    service = ProductionService(LocalStorage(tmp_path / "storage"))
    job_id = _validated_job(service, "SKU-VERIFY-BINDING")
    service.package_job(job_id)
    service.verify_job_package(job_id)

    job = service.jobs.get(job_id)
    assert job["status"] == JobLifecycle.AWAITING_APPROVAL.value
    assert job["package_verified_manifest_checksum"] == job["package_checksum"]


def test_release_rejects_missing_or_stale_verification(tmp_path):
    service = ProductionService(LocalStorage(tmp_path / "storage"))
    job_id = _approved_job(service, "SKU-STALE-VERIFY")
    job = service.jobs.get(job_id)
    job["package_verified_manifest_checksum"] = "0" * 64
    service.jobs.save(job)

    with pytest.raises(LabelosException) as error:
        service.release(job_id)

    assert error.value.error.code == "RELEASE_VERIFICATION_REQUIRED"


def test_approval_uses_checksum_of_packaged_artwork(tmp_path):
    service = ProductionService(LocalStorage(tmp_path / "storage"))
    job_id = _validated_job(service, "SKU-PACKAGED-HASH")
    service.package_job(job_id)
    service.verify_job_package(job_id)
    job = service.jobs.get(job_id)

    assert job["package_artwork_checksum"]
    # Simulate an input checksum from an earlier artwork revision. Approval must
    # still bind to the bytes written into the release package.
    job["artwork_checksum"] = "a" * 64
    service.jobs.save(job)
    with pytest.raises(LabelosException) as error:
        service.approve(job_id, approver="qa", artwork_checksum=job["artwork_checksum"])

    assert error.value.error.code == "APPROVAL_CHECKSUM_MISMATCH"


def test_release_rejects_approval_checksum_not_bound_to_package(tmp_path):
    service = ProductionService(LocalStorage(tmp_path / "storage"))
    job_id = _approved_job(service, "SKU-RELEASE-HASH")
    job = service.jobs.get(job_id)
    job["approval_result"]["artwork_checksum"] = "f" * 64
    service.jobs.save(job)

    with pytest.raises(LabelosException) as error:
        service.release(job_id)

    assert error.value.error.code == "RELEASE_CHECKSUM_MISMATCH"


def test_verified_approval_releases_successfully(tmp_path):
    service = ProductionService(LocalStorage(tmp_path / "storage"))

    released = service.release(_approved_job(service, "SKU-RELEASED"))

    assert released["status"] == JobLifecycle.RELEASED.value


@pytest.fixture()
def bridge(tmp_path, monkeypatch):
    token = "bridge-token"
    monkeypatch.setenv("LABELOS_BRIDGE_TOKEN", token)
    monkeypatch.setenv("LABELOS_TEMPLATES_PATH", str(tmp_path / "templates"))
    monkeypatch.setenv("LABELOS_BRIDGE_OUTPUT_PATH", str(tmp_path / "generated"))
    templates = tmp_path / "templates"
    templates.mkdir()
    (templates / "alternative-syrup.ai").write_bytes(b"%PDF-PLACEHOLDER")
    return TestClient(create_bridge_app()), token


def _generate_body(export_formats: list[str], *, dry_run: bool = True) -> dict:
    return {
        "product_data": _product("ALT-SYR-MANGO-001"),
        "template_path": "alternative-syrup.ai",
        "export_formats": export_formats,
        "dry_run": dry_run,
    }


@pytest.mark.parametrize("formats", [[], ["pfd"], ["pdf", "jpg"]])
def test_bridge_rejects_empty_or_unsupported_export_formats(bridge, formats):
    client, token = bridge

    response = client.post(
        "/generate",
        headers={"Authorization": f"Bearer {token}"},
        json=_generate_body(formats),
    )

    assert response.status_code == 400
    assert response.json()["result"]["error"]["code"] == "INVALID_EXPORT_FORMATS"


def test_bridge_rejects_success_without_outputs(bridge):
    client, token = bridge
    with patch(
        "illustrator_bridge.server.run_illustrator_job",
        return_value={"success": True, "outputs": []},
    ):
        response = client.post(
            "/generate",
            headers={"Authorization": f"Bearer {token}"},
            json=_generate_body(["pdf"], dry_run=False),
        )

    assert response.status_code == 500
    assert response.json()["result"]["error"]["code"] == "NO_OUTPUTS"


def test_bridge_accepts_supported_export_formats_in_dry_run(bridge):
    client, token = bridge

    response = client.post(
        "/generate",
        headers={"Authorization": f"Bearer {token}"},
        json=_generate_body(["pdf", "ai", "png"]),
    )

    assert response.status_code == 200
    assert response.json()["status"] == "ARTWORK_GENERATED_DRY_RUN"
