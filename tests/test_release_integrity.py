"""Regression tests for three release-integrity review blockers (PR #41).

P1 — successful package verification must gate release
P1 — approval must bind to the artwork actually packaged
P2 — Illustrator generation must reject invalid/empty export formats
"""

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
PASSING_ARTWORK = str(ROOT / "fixtures" / "passing-label.svg")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _passing_config() -> dict:
    return {
        "artwork": PASSING_ARTWORK,
        "width_mm": 100,
        "height_mm": 50,
        "bleed_mm": 3,
        "safe_area_mm": 2,
        "required_copy": ["Example Product", "NET 250 g"],
    }


def _product_data(sku: str, revision: str = "1.0") -> dict:
    return {
        "product": {"brand": "ALTERNATIVE", "name": "Mango Syrup", "sku": sku, "revision": revision},
        "label": {"template": "alternative-syrup.ai", "width_mm": 100, "height_mm": 50, "bleed_mm": 3},
        "copy": {"product_name": "Example Product", "net_weight": "NET 250 g"},
    }


def _build_service(tmp_path: Path) -> ProductionService:
    storage = LocalStorage(tmp_path / "storage")
    return ProductionService(storage)


def _create_and_validate(service: ProductionService, sku: str, revision: str = "1.0") -> str:
    job = service.create_or_get_job(
        product_data=_product_data(sku, revision),
        config=_passing_config(),
        mode="NORMAL",
    )
    job_id = job["job_id"]
    service.run_validate_job(job_id)
    return job_id


def _full_pipeline(service: ProductionService, sku: str, revision: str = "1.0") -> str:
    """validate → package → verify → approve → ready for release."""
    job_id = _create_and_validate(service, sku, revision)
    service.package_job(job_id)
    service.verify_job_package(job_id)
    job = service.jobs.get(job_id)
    service.approve(
        job_id,
        approver="qa",
        approved=True,
        artwork_checksum=job["package_artwork_checksum"],
    )
    return job_id


# ---------------------------------------------------------------------------
# P1 — Verification must gate release
# ---------------------------------------------------------------------------

class TestVerificationGatesRelease:
    def test_bypass_verify_approve_blocked(self, tmp_path):
        """Approval must be rejected if verify-package was never called (TECHNICALLY_VALIDATED)."""
        service = _build_service(tmp_path)
        job_id = _create_and_validate(service, "SKU-BYPASS-1")
        service.package_job(job_id)
        # Job is still TECHNICALLY_VALIDATED — approval must be blocked.
        job = service.jobs.get(job_id)
        assert job["status"] == JobLifecycle.TECHNICALLY_VALIDATED.value
        with pytest.raises(LabelosException) as exc:
            service.approve(job_id, approver="qa", approved=True)
        assert exc.value.error.code == "APPROVAL_STATE"

    def test_failed_verification_blocks_release(self, tmp_path):
        """A tampered package must cause verify to fail and prevent release."""
        service = _build_service(tmp_path)
        job_id = _create_and_validate(service, "SKU-TAMPER-1")
        service.package_job(job_id)
        job = service.jobs.get(job_id)
        # Tamper the packaged artwork to break verification.
        artwork = Path(job["package_path"]) / "passing-label.svg"
        artwork.write_text("tampered", encoding="utf-8")
        with pytest.raises(LabelosException) as exc:
            service.verify_job_package(job_id)
        assert exc.value.error.code == "PACKAGE_VERIFICATION_FAILED"

    def test_stale_verification_rejected_at_release(self, tmp_path):
        """Release must fail when package_verified_manifest_checksum doesn't match package_checksum."""
        service = _build_service(tmp_path)
        job_id = _full_pipeline(service, "SKU-STALE-1")
        job = service.jobs.get(job_id)
        # Corrupt the stored verification checksum to simulate a stale/mismatched state.
        job["package_verified_manifest_checksum"] = "0" * 64
        service.jobs.save(job)
        with pytest.raises(LabelosException) as exc:
            service.release(job_id)
        assert exc.value.error.code == "RELEASE_VERIFICATION_REQUIRED"

    def test_no_verification_rejects_release(self, tmp_path):
        """Release must fail when verification was never run (checksum absent)."""
        service = _build_service(tmp_path)
        job_id = _create_and_validate(service, "SKU-NOVERIFY-1")
        service.package_job(job_id)
        job = service.jobs.get(job_id)
        # Force status to APPROVED_FOR_PRODUCTION without verification (manual surgery).
        job["status"] = JobLifecycle.APPROVED_FOR_PRODUCTION.value
        job["approval_result"] = {
            "approver": "qa",
            "approved": True,
            "artwork_checksum": job.get("package_artwork_checksum", "x"),
            "timestamp": "2026-01-01T00:00:00+00:00",
            "comments": "",
        }
        service.jobs.save(job)
        with pytest.raises(LabelosException) as exc:
            service.release(job_id)
        assert exc.value.error.code == "RELEASE_VERIFICATION_REQUIRED"

    def test_valid_verified_release_succeeds(self, tmp_path):
        """Full valid pipeline must reach RELEASED."""
        service = _build_service(tmp_path)
        job_id = _full_pipeline(service, "SKU-VALID-1")
        released = service.release(job_id)
        assert released["status"] == JobLifecycle.RELEASED.value

    def test_verify_sets_verified_manifest_checksum(self, tmp_path):
        """verify_job_package must persist package_verified_manifest_checksum equal to package_checksum."""
        service = _build_service(tmp_path)
        job_id = _create_and_validate(service, "SKU-CHECKSUM-1")
        service.package_job(job_id)
        service.verify_job_package(job_id)
        job = service.jobs.get(job_id)
        assert job["package_verified_manifest_checksum"] is not None
        assert job["package_verified_manifest_checksum"] == job["package_checksum"]

    def test_package_clears_prior_verification(self, tmp_path):
        """package_job must clear package_verified_manifest_checksum to invalidate stale verification."""
        service = _build_service(tmp_path)
        job_id = _create_and_validate(service, "SKU-INVALIDATE-1")
        service.package_job(job_id)
        job = service.jobs.get(job_id)
        assert job["package_verified_manifest_checksum"] is None


# ---------------------------------------------------------------------------
# P1 — Approval must bind to the artwork actually packaged
# ---------------------------------------------------------------------------

class TestApprovalBindsToPackagedArtwork:
    def test_approve_without_package_blocked(self, tmp_path):
        """Approval before packaging must be blocked (no package_artwork_checksum)."""
        service = _build_service(tmp_path)
        job_id = _create_and_validate(service, "SKU-NOPACK-1")
        # Force AWAITING_APPROVAL without real package to test the checksum gate.
        job = service.jobs.get(job_id)
        job["status"] = JobLifecycle.AWAITING_APPROVAL.value
        service.jobs.save(job)
        with pytest.raises(LabelosException) as exc:
            service.approve(job_id, approver="qa", approved=True)
        assert exc.value.error.code == "APPROVAL_REQUIRES_PACKAGE"

    def test_absent_checksum_rejected(self, tmp_path):
        """Approval must fail when package_artwork_checksum is absent."""
        service = _build_service(tmp_path)
        job_id = _create_and_validate(service, "SKU-ABSENT-1")
        service.package_job(job_id)
        service.verify_job_package(job_id)
        job = service.jobs.get(job_id)
        # Manually wipe the checksum to simulate an absent value.
        job["package_artwork_checksum"] = None
        service.jobs.save(job)
        with pytest.raises(LabelosException) as exc:
            service.approve(job_id, approver="qa", approved=True)
        assert exc.value.error.code == "APPROVAL_REQUIRES_PACKAGE"

    def test_stale_checksum_rejected(self, tmp_path):
        """Providing an old/stale artwork checksum must be rejected at approval."""
        service = _build_service(tmp_path)
        job_id = _create_and_validate(service, "SKU-STALE-CHECK-1")
        service.package_job(job_id)
        service.verify_job_package(job_id)
        stale_checksum = "a" * 64
        with pytest.raises(LabelosException) as exc:
            service.approve(
                job_id, approver="qa", approved=True, artwork_checksum=stale_checksum
            )
        assert exc.value.error.code == "APPROVAL_CHECKSUM_MISMATCH"

    def test_valid_exact_match_approval_and_release(self, tmp_path):
        """Approval with the exact packaged artwork checksum must succeed end-to-end."""
        service = _build_service(tmp_path)
        job_id = _create_and_validate(service, "SKU-EXACT-1")
        service.package_job(job_id)
        service.verify_job_package(job_id)
        job = service.jobs.get(job_id)
        exact = job["package_artwork_checksum"]
        service.approve(job_id, approver="qa", approved=True, artwork_checksum=exact)
        released = service.release(job_id)
        assert released["status"] == JobLifecycle.RELEASED.value

    def test_release_blocked_on_checksum_mismatch(self, tmp_path):
        """Release must fail if approval artwork_checksum doesn't match package_artwork_checksum."""
        service = _build_service(tmp_path)
        job_id = _full_pipeline(service, "SKU-REL-MISMATCH-1")
        job = service.jobs.get(job_id)
        # Corrupt the approval checksum (post-approval surgery).
        job["approval_result"]["artwork_checksum"] = "b" * 64
        service.jobs.save(job)
        with pytest.raises(LabelosException) as exc:
            service.release(job_id)
        assert exc.value.error.code == "RELEASE_CHECKSUM_MISMATCH"

    def test_package_job_sets_package_artwork_checksum(self, tmp_path):
        """package_job must persist package_artwork_checksum from the manifest."""
        service = _build_service(tmp_path)
        job_id = _create_and_validate(service, "SKU-PAC-HASH-1")
        service.package_job(job_id)
        job = service.jobs.get(job_id)
        assert job["package_artwork_checksum"] is not None
        assert len(job["package_artwork_checksum"]) == 64


# ---------------------------------------------------------------------------
# P2 — Illustrator must reject invalid/empty export formats and zero outputs
# ---------------------------------------------------------------------------

@pytest.fixture()
def bridge(tmp_path, monkeypatch):
    token = "bridge-token"
    monkeypatch.setenv("LABELOS_BRIDGE_TOKEN", token)
    monkeypatch.setenv("LABELOS_TEMPLATES_PATH", str(tmp_path / "templates"))
    monkeypatch.setenv("LABELOS_BRIDGE_OUTPUT_PATH", str(tmp_path / "generated"))
    (tmp_path / "templates").mkdir()
    (tmp_path / "templates" / "alternative-syrup.ai").write_bytes(b"%PDF-PLACEHOLDER")
    client = TestClient(create_bridge_app())
    return client, token


def _generate_body(export_formats=None):
    return {
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
            "copy": {"product_name": "Example Product", "net_weight": "NET 250 g"},
        },
        "template_path": "alternative-syrup.ai",
        "export_formats": export_formats if export_formats is not None else ["pdf"],
        "dry_run": True,
    }


class TestIllustratorExportFormats:
    def test_empty_export_formats_rejected(self, bridge):
        client, token = bridge
        resp = client.post(
            "/generate",
            headers={"Authorization": "Bearer " + token},
            json=_generate_body(export_formats=[]),
        )
        assert resp.status_code == 400
        assert resp.json()["result"]["error"]["code"] == "INVALID_EXPORT_FORMATS"

    def test_typo_format_rejected(self, bridge):
        """'pfd' is a common typo for 'pdf' and must be rejected."""
        client, token = bridge
        resp = client.post(
            "/generate",
            headers={"Authorization": "Bearer " + token},
            json=_generate_body(export_formats=["pfd"]),
        )
        assert resp.status_code == 400
        assert resp.json()["result"]["error"]["code"] == "INVALID_EXPORT_FORMATS"

    def test_mixed_invalid_formats_rejected(self, bridge):
        """A list with one valid and one invalid format must still be rejected."""
        client, token = bridge
        resp = client.post(
            "/generate",
            headers={"Authorization": "Bearer " + token},
            json=_generate_body(export_formats=["pdf", "jpg"]),
        )
        assert resp.status_code == 400
        assert resp.json()["result"]["error"]["code"] == "INVALID_EXPORT_FORMATS"

    def test_zero_output_success_rejected(self, bridge):
        """A live Illustrator result claiming success with zero outputs must be rejected."""
        client, token = bridge
        body = _generate_body(export_formats=["pdf"])
        body["dry_run"] = False
        with patch(
            "illustrator_bridge.server.run_illustrator_job",
            return_value={"success": True, "outputs": []},
        ):
            resp = client.post(
                "/generate",
                headers={"Authorization": "Bearer " + token},
                json=body,
            )
        assert resp.status_code == 500
        assert resp.json()["result"]["error"]["code"] == "NO_OUTPUTS"

    def test_valid_pdf_format_accepted(self, bridge):
        """A dry-run with a valid single format must succeed."""
        client, token = bridge
        resp = client.post(
            "/generate",
            headers={"Authorization": "Bearer " + token},
            json=_generate_body(export_formats=["pdf"]),
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_valid_multi_format_accepted(self, bridge):
        """A dry-run with all supported formats must succeed."""
        client, token = bridge
        resp = client.post(
            "/generate",
            headers={"Authorization": "Bearer " + token},
            json=_generate_body(export_formats=["pdf", "ai", "png"]),
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True
