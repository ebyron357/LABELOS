"""Authenticated LABELOS HTTP API."""

from __future__ import annotations

import os
import secrets
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from labelos import __version__
from labelos.errors import INPUT_ERROR, LabelosException
from labelos.jobs import ProductionService, report_to_api_result
from labelos.models import LabelSpec
from labelos.observability import configure_logging, log_event, log_operation
from labelos.package import create_package, verify_package
from labelos.security import resolve_under, sanitize_job_id
from labelos.storage import get_storage
from labelos.validate import validate

configure_logging(os.environ.get("LABELOS_LOG_LEVEL", "INFO"))


def _api_token() -> str:
    token = os.environ.get("LABELOS_API_TOKEN", "").strip()
    if not token:
        raise RuntimeError(
            "LABELOS_API_TOKEN must be set to a non-empty secret before serving the API"
        )
    return token


def require_bearer(authorization: str | None = Header(default=None)) -> None:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token")
    provided = authorization.removeprefix("Bearer ").strip()
    expected = _api_token()
    if not provided or not secrets.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="Unauthorized")


class ApiEnvelope(BaseModel):
    success: bool
    job_id: str | None = None
    status: str
    exit_code: int = 0
    stdout: str = ""
    stderr: str = ""
    timestamp: str
    result: dict[str, Any] = Field(default_factory=dict)


def envelope(
    *,
    success: bool,
    status: str,
    result: dict[str, Any] | None = None,
    job_id: str | None = None,
    exit_code: int = 0,
    stdout: str = "",
    stderr: str = "",
) -> dict[str, Any]:
    return ApiEnvelope(
        success=success,
        job_id=job_id,
        status=status,
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        timestamp=datetime.now(timezone.utc).isoformat(),
        result=result or {},
    ).model_dump()


class ValidateRequest(BaseModel):
    config: dict[str, Any] | None = None
    config_path: str | None = None
    job_id: str | None = None
    root: str | None = None


class PackageRequest(BaseModel):
    config: dict[str, Any] | None = None
    destination: str | None = None
    job_id: str | None = None
    root: str | None = None


class VerifyRequest(BaseModel):
    destination: str | None = None
    job_id: str | None = None


class CreateJobRequest(BaseModel):
    config: dict[str, Any]
    product_data: dict[str, Any] | None = None
    artwork_path: str | None = None
    mode: str = "NORMAL"
    operator: str = "api"
    execution_id: str | None = None
    template_checksum: str | None = None
    auto_validate: bool = False


class ApproveRequest(BaseModel):
    approver: str
    comments: str = ""
    approved: bool = True
    artwork_checksum: str | None = None


def create_app(service: ProductionService | None = None) -> FastAPI:
    app = FastAPI(
        title="LABELOS API",
        version=__version__,
        description="Authenticated HTTP facade over the LABELOS validation engine",
    )
    production = service or ProductionService(get_storage())

    @app.exception_handler(LabelosException)
    async def _labelos_error(_request: Request, exc: LabelosException) -> JSONResponse:
        payload = envelope(
            success=False,
            status=exc.error.code,
            exit_code=1,
            stderr=exc.error.message,
            result={"error": exc.error.to_dict()},
            job_id=None,
        )
        return JSONResponse(status_code=exc.http_status, content=payload)

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return envelope(
            success=True,
            status="ok",
            result={"service": "labelos-api", "version": __version__},
        )

    @app.get("/ready")
    async def ready() -> JSONResponse:
        """Readiness probe: storage must be writable and the API token configured."""
        checks: dict[str, Any] = {}
        try:
            production.storage.ensure_layout()
            probe = production.storage.path("jobs", "index.json")
            checks["storage"] = {
                "ready": probe.parent.is_dir() and os.access(probe.parent, os.W_OK),
                "path": str(production.storage.root),
            }
        except (OSError, LabelosException) as error:
            checks["storage"] = {"ready": False, "error": str(error)}
        try:
            _api_token()
            checks["api_token"] = {"ready": True}
        except RuntimeError as error:
            checks["api_token"] = {"ready": False, "error": str(error)}
        ok = all(entry.get("ready") for entry in checks.values())
        payload = envelope(
            success=ok,
            status="ready" if ok else "not_ready",
            exit_code=0 if ok else 1,
            result={"service": "labelos-api", "version": __version__, "checks": checks},
        )
        return JSONResponse(status_code=200 if ok else 503, content=payload)

    @app.get("/doctor", dependencies=[Depends(require_bearer)])
    async def doctor() -> dict[str, Any]:
        with log_operation("doctor"):
            result = production.doctor()
        return envelope(success=True, status="ok", result=result, exit_code=0)

    @app.post("/validate", dependencies=[Depends(require_bearer)])
    async def validate_endpoint(body: ValidateRequest) -> dict[str, Any]:
        with log_operation("validate", job_id=body.job_id):
            if body.job_id:
                job = production.run_validate_job(body.job_id)
                success = job.get("validation_result", {}).get("overall") == "PASS"
                return envelope(
                    success=success,
                    status="PASS" if success else "REJECTED_VALIDATION",
                    job_id=job["job_id"],
                    exit_code=0 if success else 1,
                    result=job.get("validation_result") or {},
                )

            config = body.config
            root = Path(body.root) if body.root else Path.cwd()
            if body.config_path:
                config_path = resolve_under(root, body.config_path, field="config_path")
                import json

                config = json.loads(config_path.read_text(encoding="utf-8"))
                root = config_path.parent
            if not isinstance(config, dict):
                raise LabelosException(
                    "config or config_path is required",
                    code="CONFIG_REQUIRED",
                    category=INPUT_ERROR,
                )
            result = production.validate_config(config, root=root)
            success = result["overall"] == "PASS"
            return envelope(
                success=success,
                status="PASS" if success else "REJECTED_VALIDATION",
                exit_code=0 if success else 1,
                result=result,
            )

    @app.post("/package", dependencies=[Depends(require_bearer)])
    async def package_endpoint(body: PackageRequest) -> dict[str, Any]:
        with log_operation("package", job_id=body.job_id):
            if body.job_id:
                job = production.package_job(body.job_id)
                return envelope(
                    success=True,
                    status="PACKAGED",
                    job_id=job["job_id"],
                    result={
                        "package_path": job.get("package_path"),
                        "package_checksum": job.get("package_checksum"),
                    },
                )
            if not body.config or not body.destination:
                raise LabelosException(
                    "config and destination are required when job_id is omitted",
                    code="PACKAGE_INPUT",
                    category=INPUT_ERROR,
                )
            root = Path(body.root) if body.root else Path.cwd()
            storage_root = production.storage.root
            destination = resolve_under(storage_root, body.destination, field="destination")
            spec = LabelSpec.from_dict(body.config, root)
            report = validate(spec)
            if not report.passed:
                return envelope(
                    success=False,
                    status="REJECTED_VALIDATION",
                    exit_code=1,
                    result=report_to_api_result(report),
                )
            manifest = create_package(spec, report, destination)
            return envelope(
                success=True,
                status="PACKAGED",
                result={
                    "package_path": str(destination),
                    "manifest": str(manifest),
                    "validation": report_to_api_result(report),
                },
            )

    @app.post("/verify-package", dependencies=[Depends(require_bearer)])
    async def verify_endpoint(body: VerifyRequest) -> dict[str, Any]:
        with log_operation("verify-package", job_id=body.job_id):
            if body.job_id:
                job = production.verify_job_package(body.job_id)
                return envelope(
                    success=True,
                    status="VERIFIED",
                    job_id=job["job_id"],
                    result={"package_path": job.get("package_path"), "failures": []},
                )
            if not body.destination:
                raise LabelosException(
                    "destination or job_id is required",
                    code="VERIFY_INPUT",
                    category=INPUT_ERROR,
                )
            destination = Path(body.destination).resolve()
            # Allow verify of absolute paths under storage, or explicit temp paths for tests.
            storage_root = production.storage.root
            try:
                destination.relative_to(storage_root)
            except ValueError:
                temp_root = Path(tempfile.gettempdir()).resolve()
                try:
                    destination.relative_to(temp_root)
                except ValueError as error:
                    raise LabelosException(
                        "destination must be under LABELOS_STORAGE_PATH",
                        code="PATH_TRAVERSAL",
                        category=INPUT_ERROR,
                    ) from error
            failures = verify_package(destination)
            success = not failures
            return envelope(
                success=success,
                status="VERIFIED" if success else "PACKAGE_VERIFICATION_FAILED",
                exit_code=0 if success else 1,
                result={"failures": failures, "package_path": str(destination)},
            )

    @app.post("/jobs", dependencies=[Depends(require_bearer)])
    async def create_job(body: CreateJobRequest) -> dict[str, Any]:
        with log_operation("jobs.create"):
            if body.mode not in {"NORMAL", "RERUN", "NEW_REVISION"}:
                raise LabelosException(
                    "mode must be NORMAL, RERUN, or NEW_REVISION",
                    code="INVALID_MODE",
                    category=INPUT_ERROR,
                )
            job = production.create_or_get_job(
                product_data=body.product_data,
                config=body.config,
                artwork_path=body.artwork_path,
                mode=body.mode,  # type: ignore[arg-type]
                operator=body.operator,
                execution_id=body.execution_id,
                template_checksum=body.template_checksum,
            )
            if body.auto_validate and job.get("status") != "DUPLICATE_SKIPPED":
                job = production.run_validate_job(job["job_id"])
            return envelope(
                success=True,
                status=job.get("status", "created"),
                job_id=job["job_id"],
                result=job,
            )

    @app.get("/jobs/{job_id}", dependencies=[Depends(require_bearer)])
    async def get_job(job_id: str) -> dict[str, Any]:
        job = production.jobs.get(sanitize_job_id(job_id))
        return envelope(success=True, status=job["status"], job_id=job["job_id"], result=job)

    @app.get("/jobs/{job_id}/report", dependencies=[Depends(require_bearer)])
    async def get_report(job_id: str) -> dict[str, Any]:
        job = production.jobs.get(sanitize_job_id(job_id))
        report = job.get("validation_result") or {}
        return envelope(
            success=report.get("overall") == "PASS",
            status=job["status"],
            job_id=job["job_id"],
            result=report,
        )

    @app.get("/jobs/{job_id}/package", dependencies=[Depends(require_bearer)])
    async def get_package(job_id: str) -> Any:
        job = production.jobs.get(sanitize_job_id(job_id))
        package_path = job.get("package_path")
        if not package_path:
            raise LabelosException(
                "Package not available for job",
                code="PACKAGE_MISSING",
                category=INPUT_ERROR,
                http_status=404,
            )
        manifest = Path(package_path) / "manifest.json"
        if not manifest.is_file():
            raise LabelosException(
                "Package manifest missing",
                code="PACKAGE_MISSING",
                category=INPUT_ERROR,
                http_status=404,
            )
        return FileResponse(manifest, media_type="application/json", filename="manifest.json")

    @app.post("/jobs/{job_id}/approve", dependencies=[Depends(require_bearer)])
    async def approve_job(job_id: str, body: ApproveRequest) -> dict[str, Any]:
        job = production.approve(
            sanitize_job_id(job_id),
            approver=body.approver,
            comments=body.comments,
            approved=body.approved,
            artwork_checksum=body.artwork_checksum,
        )
        return envelope(
            success=bool((job.get("approval_result") or {}).get("approved")),
            status=job["status"],
            job_id=job["job_id"],
            result=job.get("approval_result") or {},
        )

    @app.post("/jobs/{job_id}/release", dependencies=[Depends(require_bearer)])
    async def release_job(job_id: str) -> dict[str, Any]:
        job = production.release(sanitize_job_id(job_id))
        return envelope(
            success=True,
            status=job["status"],
            job_id=job["job_id"],
            result={"final_status": job.get("final_status"), "package_path": job.get("package_path")},
        )

    return app


app = create_app()


def resolve_listen_port() -> int:
    """Prefer platform PORT (Render) over LABELOS_API_PORT for public HTTP binding."""
    return int(os.environ.get("PORT") or os.environ.get("LABELOS_API_PORT", "8080"))


def main() -> None:
    import uvicorn

    host = os.environ.get("LABELOS_API_HOST", "0.0.0.0")
    port = resolve_listen_port()
    # Touch token early so misconfiguration fails closed at startup.
    _api_token()
    log_event(operation="api.start", status="ok", host=host, port=port)
    uvicorn.run("labelos.api:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
