"""Regression tests for closeout hardening.

Covers:
* release-time atomic package re-verification (tamper after verification)
* the real callas pdfToolbox CLI adapter status normalization
* ``labelos doctor`` production dependency states
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from labelos import doctor as doctor_module
from labelos.errors import LabelosException
from labelos.jobs import ProductionService
from labelos.preflight import (
    FAIL,
    NOT_CONFIGURED,
    PASS,
    TOOL_ERROR,
    WARNING,
    PdfToolboxAdapter,
    PdfToolboxConfig,
    load_config,
)
from labelos.schemas.lifecycle import JobLifecycle
from labelos.storage import LocalStorage

ROOT = Path(__file__).parent.parent
PASSING_ARTWORK = str(ROOT / "fixtures" / "passing-label.svg")


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
        "label": {
            "template": "alternative-syrup.ai",
            "width_mm": 100,
            "height_mm": 50,
            "bleed_mm": 3,
        },
        "copy": {"product_name": "Example Product", "net_weight": "NET 250 g"},
    }


def _approved_job(service: ProductionService, sku: str) -> str:
    job = service.create_or_get_job(product_data=_product_data(sku), config=_passing_config())
    job_id = job["job_id"]
    service.run_validate_job(job_id)
    service.package_job(job_id)
    service.verify_job_package(job_id)
    packaged = service.jobs.get(job_id)
    service.approve(
        job_id,
        approver="qa",
        approved=True,
        artwork_checksum=packaged["package_artwork_checksum"],
    )
    return job_id


# ---------------------------------------------------------------------------
# Release-time atomic re-verification
# ---------------------------------------------------------------------------

class TestReleaseReverifiesPackage:
    def test_artwork_tampered_after_verification_blocks_release(self, tmp_path):
        service = ProductionService(LocalStorage(tmp_path / "storage"))
        job_id = _approved_job(service, "SKU-TAMPER-1")
        job = service.jobs.get(job_id)
        artwork = Path(job["package_path"]) / Path(PASSING_ARTWORK).name
        artwork.write_bytes(artwork.read_bytes() + b"<!-- tampered -->")

        with pytest.raises(LabelosException) as excinfo:
            service.release(job_id)
        assert excinfo.value.error.code == "RELEASE_PACKAGE_TAMPERED"
        assert service.jobs.get(job_id)["status"] != JobLifecycle.RELEASED.value
        # Verification state is cleared so a stale verification cannot be reused.
        assert service.jobs.get(job_id)["package_verified_manifest_checksum"] is None

    def test_manifest_replaced_after_verification_blocks_release(self, tmp_path):
        service = ProductionService(LocalStorage(tmp_path / "storage"))
        job_id = _approved_job(service, "SKU-TAMPER-2")
        job = service.jobs.get(job_id)
        manifest = Path(job["package_path"]) / "manifest.json"
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        payload["artwork"]["sha256"] = "0" * 64
        manifest.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        with pytest.raises(LabelosException) as excinfo:
            service.release(job_id)
        assert excinfo.value.error.code == "RELEASE_PACKAGE_TAMPERED"
        assert service.jobs.get(job_id)["status"] != JobLifecycle.RELEASED.value

    def test_untampered_package_releases(self, tmp_path):
        service = ProductionService(LocalStorage(tmp_path / "storage"))
        job_id = _approved_job(service, "SKU-TAMPER-3")
        released = service.release(job_id)
        assert released["status"] == JobLifecycle.RELEASED.value


# ---------------------------------------------------------------------------
# callas pdfToolbox adapter (controlled command-execution boundary)
# ---------------------------------------------------------------------------

def _fake_cli(tmp_path: Path) -> Path:
    executable = tmp_path / "pdfToolbox"
    executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    executable.chmod(0o755)
    return executable


def _profile(tmp_path: Path) -> Path:
    profile = tmp_path / "approved.kfpx"
    profile.write_text("profile", encoding="utf-8")
    return profile


def _pdf(tmp_path: Path) -> Path:
    artwork = tmp_path / "artwork.pdf"
    artwork.write_bytes(b"%PDF-1.7\n%%EOF\n")
    return artwork


def _adapter(tmp_path: Path, runner, *, fixup: str | None = None) -> PdfToolboxAdapter:
    config = PdfToolboxConfig(
        executable=str(_fake_cli(tmp_path)),
        profile=str(_profile(tmp_path)),
        fixup_profile=fixup,
        timeout=30,
    )
    return PdfToolboxAdapter(config=config, runner=runner)


def _runner_writing(report: dict | str, *, returncode: int = 0):
    def runner(command, **_kwargs):
        report_path = next(
            Path(arg.split("=", 1)[1]) for arg in command if arg.startswith("--reportpath=")
        )
        report_path.write_text(
            report if isinstance(report, str) else json.dumps(report), encoding="utf-8"
        )
        return subprocess.CompletedProcess(command, returncode, stdout="", stderr="")

    return runner


class TestPdfToolboxAdapter:
    def test_not_configured_without_executable(self, tmp_path):
        adapter = PdfToolboxAdapter(
            config=PdfToolboxConfig(executable=None, profile=None, fixup_profile=None, timeout=30)
        )
        result = adapter.run(str(_pdf(tmp_path)))
        assert result.status == NOT_CONFIGURED
        assert result.enabled is False
        assert result.blocking is True

    def test_pass_when_report_has_no_hits(self, tmp_path):
        adapter = _adapter(tmp_path, _runner_writing({"summary": {"errors": 0, "warnings": 0}}))
        result = adapter.run(str(_pdf(tmp_path)))
        assert result.status == PASS
        assert result.blocking is False
        assert Path(result.report_path).is_file()

    def test_warning_is_distinct_from_failure(self, tmp_path):
        adapter = _adapter(tmp_path, _runner_writing({"summary": {"errors": 0, "warnings": 2}}))
        result = adapter.run(str(_pdf(tmp_path)))
        assert result.status == WARNING
        assert result.warnings == 2
        assert result.blocking is False

    def test_fail_when_report_has_errors(self, tmp_path):
        adapter = _adapter(
            tmp_path,
            _runner_writing({"hits": [{"severity": "error"}, {"severity": "warning"}]}, returncode=1),
        )
        result = adapter.run(str(_pdf(tmp_path)))
        assert result.status == FAIL
        assert result.errors == 1
        assert result.blocking is True

    def test_tool_error_when_no_report_written(self, tmp_path):
        def runner(command, **_kwargs):
            return subprocess.CompletedProcess(command, 9, stdout="", stderr="crash")

        adapter = _adapter(tmp_path, runner)
        result = adapter.run(str(_pdf(tmp_path)))
        assert result.status == TOOL_ERROR
        assert result.blocking is True

    def test_tool_error_when_report_is_unparseable(self, tmp_path):
        adapter = _adapter(tmp_path, _runner_writing("{not json"))
        result = adapter.run(str(_pdf(tmp_path)))
        assert result.status == TOOL_ERROR

    def test_tool_error_on_timeout(self, tmp_path):
        def runner(command, **_kwargs):
            raise subprocess.TimeoutExpired(command, 30)

        result = _adapter(tmp_path, runner).run(str(_pdf(tmp_path)))
        assert result.status == TOOL_ERROR
        assert "timed out" in result.message

    def test_source_pdf_is_never_overwritten(self, tmp_path):
        artwork = _pdf(tmp_path)
        original = artwork.read_bytes()

        def runner(command, **_kwargs):
            output = next(
                Path(arg.split("=", 1)[1]) for arg in command if arg.startswith("--outputfile=")
            )
            output.write_bytes(b"%PDF-1.7 corrected\n")
            report_path = next(
                Path(arg.split("=", 1)[1]) for arg in command if arg.startswith("--reportpath=")
            )
            report_path.write_text(json.dumps({"summary": {"errors": 0, "warnings": 0}}))
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        result = _adapter(tmp_path, runner, fixup=str(tmp_path / "fixups.kfpx")).run(str(artwork))
        assert result.status == PASS
        assert artwork.read_bytes() == original
        assert result.corrected_pdf is not None
        assert Path(result.corrected_pdf) != artwork
        assert Path(result.corrected_pdf).is_file()

    def test_missing_artwork_is_tool_error(self, tmp_path):
        adapter = _adapter(tmp_path, _runner_writing({"summary": {"errors": 0, "warnings": 0}}))
        result = adapter.run(str(tmp_path / "absent.pdf"))
        assert result.status == TOOL_ERROR

    def test_load_config_reads_environment(self, monkeypatch):
        monkeypatch.setenv("LABELOS_PDFTOOLBOX_PATH", "/opt/callas/pdfToolbox")
        monkeypatch.setenv("LABELOS_PDFTOOLBOX_PROFILE", "/opt/callas/profile.kfpx")
        monkeypatch.setenv("LABELOS_PDFTOOLBOX_TIMEOUT", "bogus")
        config = load_config()
        assert config.configured is True
        assert config.timeout == 300

    def test_job_preflight_fails_closed_when_required(self, tmp_path, monkeypatch):
        monkeypatch.delenv("LABELOS_PDFTOOLBOX_PATH", raising=False)
        monkeypatch.delenv("LABELOS_PDFTOOLBOX_PROFILE", raising=False)
        service = ProductionService(LocalStorage(tmp_path / "storage"))
        job = service.create_or_get_job(
            product_data=_product_data("SKU-PREFLIGHT-1"), config=_passing_config()
        )
        with pytest.raises(LabelosException) as excinfo:
            service.run_preflight(job["job_id"], required=True)
        assert excinfo.value.error.code == "PREPRESS_REQUIRED"
        recorded = service.jobs.get(job["job_id"])["preflight_result"]
        assert recorded["status"] == NOT_CONFIGURED
        assert recorded["blocking"] is True

    def test_job_preflight_records_result_when_optional(self, tmp_path):
        service = ProductionService(LocalStorage(tmp_path / "storage"))
        job = service.create_or_get_job(
            product_data=_product_data("SKU-PREFLIGHT-2"), config=_passing_config()
        )
        updated = service.run_preflight(job["job_id"])
        assert updated["preflight_result"]["status"] == NOT_CONFIGURED


# ---------------------------------------------------------------------------
# labelos doctor
# ---------------------------------------------------------------------------

class TestDoctor:
    def test_states_are_from_the_allowed_vocabulary(self, tmp_path, monkeypatch):
        monkeypatch.setenv("LABELOS_STORAGE_PATH", str(tmp_path))
        report = doctor_module.run_doctor()
        assert set(report["components"]) >= {
            "labelos_core",
            "python_environment",
            "storage",
            "api",
            "illustrator_bridge",
            "adobe_illustrator",
            "pdftoolbox",
            "n8n",
            "printer_profiles",
            "product_schemas",
            "production_config",
        }
        for entry in report["components"].values():
            assert entry["state"] in doctor_module.VALID_STATES

    def test_unconfigured_dependencies_are_not_ready(self, monkeypatch):
        for name in (
            "LABELOS_PDFTOOLBOX_PATH",
            "LABELOS_PDFTOOLBOX_PROFILE",
            "LABELOS_BRIDGE_URL",
            "LABELOS_N8N_WORKFLOW_ID",
            "LABELOS_PRINTER_PROFILES_PATH",
            "LABELOS_PRODUCT_DATA_PATH",
        ):
            monkeypatch.delenv(name, raising=False)
        report = doctor_module.run_doctor()
        for name in ("pdftoolbox", "illustrator_bridge", "n8n", "printer_profiles", "product_schemas"):
            assert report["components"][name]["state"] != doctor_module.READY
        assert report["passed"] is False
        assert "pdftoolbox" in report["blocking"]

    def test_storage_state_reflects_the_filesystem(self, tmp_path, monkeypatch):
        monkeypatch.setenv("LABELOS_STORAGE_PATH", str(tmp_path / "present"))
        (tmp_path / "present").mkdir()
        assert doctor_module.run_doctor()["components"]["storage"]["state"] == doctor_module.READY
        monkeypatch.setenv("LABELOS_STORAGE_PATH", str(tmp_path / "absent"))
        assert doctor_module.run_doctor()["components"]["storage"]["state"] == doctor_module.MISSING

    def test_short_api_token_is_unhealthy(self, monkeypatch):
        monkeypatch.setenv("LABELOS_API_TOKEN", "short")
        assert doctor_module.run_doctor()["components"]["api"]["state"] == doctor_module.UNHEALTHY
