"""Job identity, idempotency, audit trail, and release orchestration."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from .errors import (
    APPROVAL_ERROR,
    DUPLICATE_SKIPPED,
    INPUT_ERROR,
    LABEL_VALIDATION_FAILURE,
    PACKAGE_ERROR,
    PACKAGE_VERIFICATION_FAILED,
    LabelosException,
)
from .models import LabelSpec, Report
from .observability import log_event
from .package import create_package, sha256_file, verify_package
from .preflight import PreflightResult, get_preflight_adapter
from .schemas.lifecycle import LIFECYCLE_TRANSITIONS, JobLifecycle
from .schemas.product import ProductRecord, parse_product_record
from .security import sanitize_job_id, sanitize_revision, sanitize_sku
from .storage import LocalStorage, get_storage
from .validate import validate

RunMode = Literal["NORMAL", "RERUN", "NEW_REVISION"]


def new_job_id() -> str:
    return f"JOB-{uuid.uuid4().hex[:12].upper()}"


def checksum_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def checksum_json(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return checksum_bytes(encoded)


def compute_identity(
    *,
    sku: str,
    revision: str,
    template_checksum: str | None,
    product_data_checksum: str,
    artwork_checksum: str | None,
    config_checksum: str,
) -> str:
    material = "|".join(
        [
            sanitize_sku(sku),
            sanitize_revision(revision),
            template_checksum or "",
            product_data_checksum,
            artwork_checksum or "",
            config_checksum,
        ]
    )
    return checksum_bytes(material.encode("utf-8"))


def report_to_api_result(report: Report) -> dict[str, Any]:
    """Convert engine Report into structured n8n-friendly validation result."""
    failed = [issue.code for issue in report.issues if issue.severity == "error"]
    checks: list[dict[str, str]] = []
    for name in report.checks:
        checks.append(
            {
                "code": name.upper().replace("-", "_").replace(":", "_"),
                "status": "PASS",
                "description": f"Completed check: {name}",
            }
        )
    for issue in report.issues:
        checks.append(
            {
                "code": issue.code,
                "status": "FAIL" if issue.severity == "error" else "WARN",
                "description": issue.message,
            }
        )
    return {
        "overall": "PASS" if report.passed else "FAIL",
        "passed": report.passed,
        "failed": failed,
        "checks": checks,
        "issues": [issue.__dict__ for issue in report.issues],
        "metadata": report.metadata,
        "source": report.source,
    }


class JobStore:
    """Filesystem-backed system-of-record for production jobs."""

    def __init__(self, storage: LocalStorage | None = None) -> None:
        self.storage = storage or get_storage()
        self.storage.ensure_layout()
        self._index_path = self.storage.path("jobs", "index.json")
        if not self._index_path.exists():
            self._index_path.write_text("{}\n", encoding="utf-8")

    def _load_index(self) -> dict[str, Any]:
        return json.loads(self._index_path.read_text(encoding="utf-8") or "{}")

    def _save_index(self, index: dict[str, Any]) -> None:
        self._index_path.write_text(json.dumps(index, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def get(self, job_id: str) -> dict[str, Any]:
        job_id = sanitize_job_id(job_id)
        return self.storage.read_json(f"jobs/{job_id}/job.json")

    def find_by_identity(self, identity: str) -> dict[str, Any] | None:
        index = self._load_index()
        job_id = index.get("identities", {}).get(identity)
        if not job_id:
            return None
        try:
            return self.get(job_id)
        except LabelosException:
            return None

    def save(self, job: dict[str, Any]) -> dict[str, Any]:
        job_id = sanitize_job_id(job["job_id"])
        relative = f"jobs/{job_id}/job.json"
        path = self.storage.path(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(job, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        index = self._load_index()
        identities = index.setdefault("identities", {})
        jobs = index.setdefault("jobs", {})
        if job.get("identity"):
            identities[job["identity"]] = job_id
        jobs[job_id] = {
            "sku": job.get("sku"),
            "revision": job.get("revision"),
            "status": job.get("status"),
            "updated_at": job.get("updated_at"),
        }
        self._save_index(index)
        return job

    def transition(self, job: dict[str, Any], new_status: JobLifecycle) -> dict[str, Any]:
        current = JobLifecycle(job["status"])
        allowed = LIFECYCLE_TRANSITIONS.get(current, set())
        if new_status not in allowed and current != new_status:
            raise LabelosException(
                f"Illegal lifecycle transition {current.value} → {new_status.value}",
                code="ILLEGAL_TRANSITION",
                category=INPUT_ERROR,
            )
        job["status"] = new_status.value
        job["updated_at"] = datetime.now(timezone.utc).isoformat()
        history = job.setdefault("history", [])
        history.append(
            {
                "status": new_status.value,
                "timestamp": job["updated_at"],
            }
        )
        return self.save(job)


def create_job_record(
    *,
    sku: str,
    revision: str,
    identity: str,
    product_data: dict[str, Any],
    config: dict[str, Any],
    mode: RunMode,
    operator: str,
    template_checksum: str | None = None,
    artwork_checksum: str | None = None,
    config_checksum: str,
    product_data_checksum: str,
    execution_id: str | None = None,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    job_id = new_job_id()
    return {
        "job_id": job_id,
        "execution_id": execution_id or job_id,
        "sku": sanitize_sku(sku),
        "revision": sanitize_revision(revision),
        "status": JobLifecycle.DRAFT.value,
        "mode": mode,
        "identity": identity,
        "template": product_data.get("label", {}).get("template"),
        "template_checksum": template_checksum,
        "product_data_checksum": product_data_checksum,
        "artwork_checksum": artwork_checksum,
        "config_checksum": config_checksum,
        "validation_result": None,
        "preflight_result": None,
        "approval_result": None,
        "package_checksum": None,
        "package_path": None,
        "package_artwork_checksum": None,
        "package_verified_manifest_checksum": None,
        "errors": [],
        "final_status": None,
        "operator": operator,
        "created_at": now,
        "updated_at": now,
        "timestamps": {"created_at": now},
        "history": [{"status": JobLifecycle.DRAFT.value, "timestamp": now}],
        "product_data": product_data,
        "config": config,
    }


class ProductionService:
    """Coordinates validation, packaging, verification, approval, and audit."""

    def __init__(self, storage: LocalStorage | None = None) -> None:
        self.storage = storage or get_storage()
        self.jobs = JobStore(self.storage)

    def doctor(self) -> dict[str, Any]:
        from .cli import _doctor

        return _doctor()

    def validate_config(self, config: dict[str, Any], *, root: Path | None = None) -> dict[str, Any]:
        work_root = root or Path.cwd()
        try:
            spec = LabelSpec.from_dict(config, work_root)
        except (TypeError, ValueError) as error:
            raise LabelosException(
                str(error),
                code="CONFIG_INVALID",
                category=INPUT_ERROR,
            ) from error
        report = validate(spec)
        result = report_to_api_result(report)
        if not report.passed:
            result["status"] = "REJECTED_VALIDATION"
            log_event(operation="validate", status="REJECTED_VALIDATION", failed=result["failed"])
        return result

    def create_or_get_job(
        self,
        *,
        product_data: dict[str, Any] | None = None,
        config: dict[str, Any],
        artwork_path: str | None = None,
        mode: RunMode = "NORMAL",
        operator: str = "api",
        execution_id: str | None = None,
        template_checksum: str | None = None,
    ) -> dict[str, Any]:
        record: ProductRecord | None = None
        if product_data is not None:
            record = parse_product_record(product_data)
            sku = record.product.sku
            revision = record.product.revision
            product_payload = record.model_dump(by_alias=True)
        else:
            sku = sanitize_sku(str(config.get("sku", "UNSPECIFIED-SKU")))
            revision = sanitize_revision(str(config.get("revision", "0.0")))
            product_payload = {"inferred_from_config": True}

        if artwork_path and "artwork" not in config:
            config = {**config, "artwork": artwork_path}

        product_checksum = checksum_json(product_payload)
        config_checksum = checksum_json(config)
        artwork_checksum = None
        candidate_artwork = artwork_path or config.get("artwork")
        if candidate_artwork:
            path = Path(str(candidate_artwork))
            if path.is_file():
                artwork_checksum = sha256_file(path)

        identity = compute_identity(
            sku=sku,
            revision=revision,
            template_checksum=template_checksum,
            product_data_checksum=product_checksum,
            artwork_checksum=artwork_checksum,
            config_checksum=config_checksum,
        )

        existing = self.jobs.find_by_identity(identity)
        if existing and mode == "NORMAL":
            skipped = {
                "job_id": existing["job_id"],
                "execution_id": existing.get("execution_id"),
                "sku": existing.get("sku"),
                "revision": existing.get("revision"),
                "status": DUPLICATE_SKIPPED,
                "final_status": DUPLICATE_SKIPPED,
                "duplicate_of": existing["job_id"],
                "identity": identity,
                "original_status": existing.get("status"),
            }
            log_event(
                operation="jobs.create",
                status=DUPLICATE_SKIPPED,
                job_id=existing["job_id"],
                sku=sku,
                revision=revision,
            )
            return skipped

        if mode == "NEW_REVISION" and record is None:
            raise LabelosException(
                "NEW_REVISION requires a product record with an explicit revision",
                code="REVISION_REQUIRED",
                category=INPUT_ERROR,
            )

        job = create_job_record(
            sku=sku,
            revision=revision,
            identity=identity,
            product_data=product_payload,
            config=config,
            mode=mode,
            operator=operator,
            template_checksum=template_checksum,
            artwork_checksum=artwork_checksum,
            config_checksum=config_checksum,
            product_data_checksum=product_checksum,
            execution_id=execution_id,
        )
        self.jobs.save(job)
        self.jobs.transition(job, JobLifecycle.DATA_READY)
        return job

    def run_validate_job(self, job_id: str, *, root: Path | None = None) -> dict[str, Any]:
        job = self.jobs.get(job_id)
        result = self.validate_config(job["config"], root=root)
        job["validation_result"] = result
        job["timestamps"]["validated_at"] = datetime.now(timezone.utc).isoformat()
        if result["overall"] != "PASS":
            job["errors"].append(
                {
                    "code": LABEL_VALIDATION_FAILURE,
                    "message": "Validation failed",
                    "failed": result["failed"],
                }
            )
            job["final_status"] = JobLifecycle.REJECTED_VALIDATION.value
            self.jobs.transition(job, JobLifecycle.REJECTED_VALIDATION)
            return job
        self.jobs.transition(job, JobLifecycle.TECHNICALLY_VALIDATED)
        return job

    def package_job(self, job_id: str, *, root: Path | None = None) -> dict[str, Any]:
        job = self.jobs.get(job_id)
        if job.get("validation_result", {}).get("overall") != "PASS":
            raise LabelosException(
                "Refusing to package artwork that has not passed validation",
                code="PACKAGE_BLOCKED",
                category=PACKAGE_ERROR,
            )
        work_root = root or Path.cwd()
        try:
            spec = LabelSpec.from_dict(job["config"], work_root)
        except (TypeError, ValueError) as error:
            raise LabelosException(str(error), code="CONFIG_INVALID", category=INPUT_ERROR) from error
        report = validate(spec)
        if not report.passed:
            raise LabelosException(
                "Validation no longer passes; packaging refused",
                code="PACKAGE_BLOCKED",
                category=LABEL_VALIDATION_FAILURE,
            )

        destination = self.storage.release_dir(job["sku"], job["revision"], job["job_id"])
        if destination.exists():
            raise LabelosException(
                "Release package destination already exists",
                code="DUPLICATE_RELEASE",
                category=PACKAGE_ERROR,
                http_status=409,
            )

        extras = {
            "product-data.json": job.get("product_data") or {},
            "config.json": job.get("config") or {},
            "job-metadata.json": {
                "job_id": job["job_id"],
                "execution_id": job["execution_id"],
                "sku": job["sku"],
                "revision": job["revision"],
                "identity": job["identity"],
                "operator": job["operator"],
                "template_checksum": job.get("template_checksum"),
                "product_data_checksum": job.get("product_data_checksum"),
                "artwork_checksum": job.get("artwork_checksum"),
                "config_checksum": job.get("config_checksum"),
            },
        }
        try:
            manifest = create_package(spec, report, destination, extras=extras)
        except FileExistsError as error:
            raise LabelosException(
                str(error),
                code="DUPLICATE_RELEASE",
                category=PACKAGE_ERROR,
                http_status=409,
            ) from error

        manifest_data = json.loads(manifest.read_text(encoding="utf-8"))
        job["package_path"] = str(destination)
        job["package_checksum"] = sha256_file(manifest)
        job["package_artwork_checksum"] = manifest_data["artwork"]["sha256"]
        # Invalidate any prior verification whenever a new package is written.
        job["package_verified_manifest_checksum"] = None
        job["timestamps"]["packaged_at"] = datetime.now(timezone.utc).isoformat()
        self.jobs.save(job)
        return job

    def verify_job_package(self, job_id: str) -> dict[str, Any]:
        job = self.jobs.get(job_id)
        package_path = job.get("package_path")
        if not package_path:
            raise LabelosException(
                "Job has no package to verify",
                code="PACKAGE_MISSING",
                category=PACKAGE_ERROR,
            )
        failures = verify_package(Path(package_path))
        job["timestamps"]["verified_at"] = datetime.now(timezone.utc).isoformat()
        if failures:
            job["errors"].append(
                {
                    "code": PACKAGE_VERIFICATION_FAILED,
                    "message": "Package verification failed",
                    "failures": failures,
                }
            )
            job["final_status"] = PACKAGE_VERIFICATION_FAILED
            self.jobs.transition(job, JobLifecycle.PACKAGE_VERIFICATION_FAILED)
            raise LabelosException(
                "Package verification failed",
                code=PACKAGE_VERIFICATION_FAILED,
                category=PACKAGE_VERIFICATION_FAILED,
                details={"failures": failures},
            )
        # Bind the verification to the current manifest checksum so release can
        # confirm the package has not changed since verification.
        job["package_verified_manifest_checksum"] = job.get("package_checksum")
        self.jobs.save(job)
        self.jobs.transition(job, JobLifecycle.AWAITING_APPROVAL)
        return job

    def run_preflight(self, job_id: str, *, enabled: bool = False) -> dict[str, Any]:
        job = self.jobs.get(job_id)
        artwork = job.get("config", {}).get("artwork")
        adapter = get_preflight_adapter()
        result: PreflightResult = adapter.run(str(artwork) if artwork else "", profile=None)
        if enabled and not result.enabled:
            raise LabelosException(
                "Commercial preflight required but Callas is not configured",
                code="PREPRESS_REQUIRED",
                category="PREPRESS_ERROR",
            )
        job["preflight_result"] = result.to_dict()
        self.jobs.save(job)
        return job

    def approve(
        self,
        job_id: str,
        *,
        approver: str,
        comments: str = "",
        approved: bool = True,
        artwork_checksum: str | None = None,
    ) -> dict[str, Any]:
        job = self.jobs.get(job_id)
        if job["status"] != JobLifecycle.AWAITING_APPROVAL.value:
            raise LabelosException(
                f"Job status {job['status']} is not awaiting approval; "
                "package verification must succeed before approving",
                code="APPROVAL_STATE",
                category=APPROVAL_ERROR,
            )
        # Bind to the checksum of the artwork that was actually packaged and verified.
        expected = job.get("package_artwork_checksum")
        if not expected:
            raise LabelosException(
                "Job has no packaged artwork checksum; create a verified package before approving",
                code="APPROVAL_REQUIRES_PACKAGE",
                category=APPROVAL_ERROR,
            )
        if artwork_checksum is None:
            artwork_checksum = expected
        if artwork_checksum != expected:
            raise LabelosException(
                "Approval checksum does not match the packaged artwork checksum",
                code="APPROVAL_CHECKSUM_MISMATCH",
                category=APPROVAL_ERROR,
                details={"expected": expected, "provided": artwork_checksum},
            )
        approval = {
            "approver": approver,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "comments": comments,
            "artwork_checksum": artwork_checksum,
            "approved": approved,
        }
        job["approval_result"] = approval
        job["timestamps"]["approval_at"] = approval["timestamp"]
        if approved:
            self.jobs.transition(job, JobLifecycle.APPROVED_FOR_PRODUCTION)
            job["final_status"] = JobLifecycle.APPROVED_FOR_PRODUCTION.value
        else:
            self.jobs.transition(job, JobLifecycle.REJECTED_BY_APPROVER)
            job["final_status"] = JobLifecycle.REJECTED_BY_APPROVER.value
        self.jobs.save(job)
        return job

    def release(self, job_id: str) -> dict[str, Any]:
        job = self.jobs.get(job_id)
        if job["status"] != JobLifecycle.APPROVED_FOR_PRODUCTION.value:
            raise LabelosException(
                "Release requires APPROVED_FOR_PRODUCTION",
                code="RELEASE_BLOCKED",
                category=APPROVAL_ERROR,
            )
        if not job.get("package_path") or not job.get("package_checksum"):
            raise LabelosException(
                "Release requires a verified package",
                code="RELEASE_PACKAGE_MISSING",
                category=PACKAGE_ERROR,
            )
        # Fail closed if verification was never run or the package changed afterward.
        verified_checksum = job.get("package_verified_manifest_checksum")
        if not verified_checksum or verified_checksum != job.get("package_checksum"):
            raise LabelosException(
                "Release requires a successful package verification matching the current package",
                code="RELEASE_VERIFICATION_REQUIRED",
                category=PACKAGE_VERIFICATION_FAILED,
            )
        approval = job.get("approval_result") or {}
        if not approval.get("approved"):
            raise LabelosException(
                "Release requires human approval bound to artwork checksum",
                code="RELEASE_APPROVAL_MISSING",
                category=APPROVAL_ERROR,
            )
        # Require the approval artwork checksum to exactly match the packaged artwork checksum.
        package_artwork_checksum = job.get("package_artwork_checksum")
        approval_artwork_checksum = approval.get("artwork_checksum")
        if not package_artwork_checksum or not approval_artwork_checksum:
            raise LabelosException(
                "Release requires artwork checksum bound to both the package and the approval",
                code="RELEASE_CHECKSUM_MISSING",
                category=APPROVAL_ERROR,
            )
        if package_artwork_checksum != approval_artwork_checksum:
            raise LabelosException(
                "Approval artwork checksum does not match the packaged artwork checksum",
                code="RELEASE_CHECKSUM_MISMATCH",
                category=APPROVAL_ERROR,
                details={
                    "package_artwork_checksum": package_artwork_checksum,
                    "approval_artwork_checksum": approval_artwork_checksum,
                },
            )
        self.jobs.transition(job, JobLifecycle.RELEASED)
        job["final_status"] = JobLifecycle.RELEASED.value
        job["timestamps"]["released_at"] = datetime.now(timezone.utc).isoformat()
        self.jobs.save(job)
        return job
