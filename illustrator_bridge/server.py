"""Illustrator Automation Bridge — workstation agent for Adobe Illustrator.

Architecture (supported on Windows production workstations):
  n8n → authenticated HTTP → this bridge → Adobe Illustrator ExtendScript (COM)
       → exported AI/PDF/PNG → LABELOS API

Illustrator is NOT assumed to be a headless cloud process. This bridge is intended
to run on a controlled machine where Adobe Illustrator is installed and licensed.

Automation mechanism:
  - Windows: win32com.client Dispatch("Illustrator.Application") + DoJavaScriptFile
  - ExtendScript replaces named text frames / placed items by stable object names
  - Locked layers (BRAND_MARK, DIELINE, PRODUCTION) are never modified by script

If Illustrator / COM is unavailable, requests fail closed with ILLUSTRATOR_ERROR.
"""

from __future__ import annotations

import json
import os
import secrets
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

# Allow importing labelos when run from repo root.
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from labelos.errors import (
    ARTWORK_GENERATION_ERROR,
    ILLUSTRATOR_ERROR,
    INPUT_ERROR,
    LabelosException,
)
from labelos.observability import configure_logging, log_event, log_operation
from labelos.package import sha256_file
from labelos.schemas.product import parse_product_record
from labelos.security import resolve_under, sanitize_token

# Only these formats are supported by the ExtendScript exporter.
SUPPORTED_EXPORT_FORMATS: frozenset[str] = frozenset({"pdf", "ai", "png"})

configure_logging(os.environ.get("LABELOS_LOG_LEVEL", "INFO"))

SCRIPT_PATH = Path(__file__).resolve().parent / "scripts" / "generate_label.jsx"


def _bridge_token() -> str:
    token = os.environ.get("LABELOS_BRIDGE_TOKEN") or os.environ.get("LABELOS_API_TOKEN", "")
    token = token.strip()
    if not token:
        raise RuntimeError("LABELOS_BRIDGE_TOKEN or LABELOS_API_TOKEN must be set")
    return token


def require_bearer(authorization: str | None = Header(default=None)) -> None:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token")
    provided = authorization.removeprefix("Bearer ").strip()
    if not provided or not secrets.compare_digest(provided, _bridge_token()):
        raise HTTPException(status_code=401, detail="Unauthorized")


class GenerateRequest(BaseModel):
    product_data: dict[str, Any]
    template_path: str
    output_dir: str | None = None
    export_formats: list[str] = Field(default_factory=lambda: ["pdf"])
    dry_run: bool = False


def illustrator_available() -> dict[str, Any]:
    if sys.platform != "win32":
        return {
            "available": False,
            "reason": "Illustrator COM automation is supported on Windows workstations only",
            "platform": sys.platform,
        }
    try:
        import win32com.client  # type: ignore
    except ImportError:
        return {
            "available": False,
            "reason": "pywin32 is not installed (required for Illustrator.Application COM)",
            "platform": sys.platform,
        }
    try:
        app = win32com.client.Dispatch("Illustrator.Application")
        version = str(getattr(app, "Version", "unknown"))
        return {"available": True, "version": version, "platform": sys.platform}
    except Exception as error:  # noqa: BLE001
        return {
            "available": False,
            "reason": f"Illustrator COM unavailable: {error}",
            "platform": sys.platform,
        }


def build_extendscript_payload(
    *,
    template: Path,
    output_dir: Path,
    variables: dict[str, str],
    export_formats: list[str],
    barcode_value: str | None,
    qr_value: str | None,
) -> dict[str, Any]:
    return {
        "templatePath": str(template),
        "outputDir": str(output_dir),
        "variables": variables,
        "exportFormats": export_formats,
        "barcodeValue": barcode_value,
        "qrValue": qr_value,
        "preserveLockedLayers": True,
        "lockedLayerNames": ["BRAND_MARK", "DIELINE", "PRODUCTION", "BACKGROUND_ART"],
    }


def run_illustrator_job(payload: dict[str, Any]) -> dict[str, Any]:
    status = illustrator_available()
    if not status.get("available"):
        raise LabelosException(
            status.get("reason", "Illustrator unavailable"),
            code="ILLUSTRATOR_UNAVAILABLE",
            category=ILLUSTRATOR_ERROR,
            http_status=503,
            details=status,
        )
    import win32com.client  # type: ignore

    if not SCRIPT_PATH.is_file():
        raise LabelosException(
            f"ExtendScript missing: {SCRIPT_PATH}",
            code="SCRIPT_MISSING",
            category=ILLUSTRATOR_ERROR,
            http_status=500,
        )

    with tempfile.TemporaryDirectory(prefix="labelos-ai-") as tmp:
        payload_path = Path(tmp) / "payload.json"
        result_path = Path(tmp) / "result.json"
        payload = {**payload, "resultPath": str(result_path)}
        payload_path.write_text(json.dumps(payload), encoding="utf-8")
        app = win32com.client.Dispatch("Illustrator.Application")
        # Prefer argument array style — DoJavaScriptFile takes path + args array.
        args = win32com.client.VARIANT(
            win32com.client.pythoncom.VT_ARRAY | win32com.client.pythoncom.VT_VARIANT,
            [str(payload_path)],
        )
        try:
            app.DoJavaScriptFile(str(SCRIPT_PATH), args)
        except Exception as error:
            raise LabelosException(
                f"Illustrator scripting failed: {error}",
                code="ILLUSTRATOR_SCRIPT_FAILED",
                category=ARTWORK_GENERATION_ERROR,
                details={"error": str(error)},
            ) from error
        if not result_path.is_file():
            raise LabelosException(
                "Illustrator script did not write a result file",
                code="ILLUSTRATOR_NO_RESULT",
                category=ARTWORK_GENERATION_ERROR,
            )
        result = json.loads(result_path.read_text(encoding="utf-8"))
        if not result.get("success"):
            raise LabelosException(
                result.get("message", "Artwork generation failed"),
                code=result.get("code", "ARTWORK_GENERATION_ERROR"),
                category=ARTWORK_GENERATION_ERROR,
                details=result,
            )
        return result


def create_bridge_app() -> FastAPI:
    app = FastAPI(title="LABELOS Illustrator Bridge", version="0.1.0")
    templates_root = Path(
        os.environ.get("LABELOS_TEMPLATES_PATH", REPO_ROOT / "templates")
    ).resolve()
    output_root = Path(
        os.environ.get("LABELOS_BRIDGE_OUTPUT_PATH", REPO_ROOT / "storage" / "generated")
    ).resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    @app.exception_handler(LabelosException)
    async def _labelos_error(_request, exc: LabelosException):
        from fastapi.responses import JSONResponse

        return JSONResponse(
            status_code=exc.http_status,
            content={
                "success": False,
                "status": exc.error.code,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "result": {"error": exc.error.to_dict()},
            },
        )

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {
            "success": True,
            "status": "ok",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "result": {"service": "labelos-illustrator-bridge", "illustrator": illustrator_available()},
        }

    @app.get("/doctor", dependencies=[Depends(require_bearer)])
    async def doctor() -> dict[str, Any]:
        info = illustrator_available()
        return {
            "success": True,
            "status": "ok" if info.get("available") else "ILLUSTRATOR_UNAVAILABLE",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "result": {
                "illustrator": info,
                "script": str(SCRIPT_PATH),
                "script_present": SCRIPT_PATH.is_file(),
                "templates_root": str(templates_root),
            },
        }

    @app.post("/generate", dependencies=[Depends(require_bearer)])
    async def generate(body: GenerateRequest) -> dict[str, Any]:
        with log_operation("illustrator.generate", dry_run=body.dry_run):
            record = parse_product_record(body.product_data)
            if not body.export_formats:
                raise LabelosException(
                    "export_formats must not be empty",
                    code="INVALID_EXPORT_FORMATS",
                    category=INPUT_ERROR,
                    http_status=400,
                )
            invalid_formats = [
                export_format
                for export_format in body.export_formats
                if export_format not in SUPPORTED_EXPORT_FORMATS
            ]
            if invalid_formats:
                raise LabelosException(
                    f"Unsupported export format(s): {invalid_formats}. Supported: pdf, ai, png",
                    code="INVALID_EXPORT_FORMATS",
                    category=INPUT_ERROR,
                    http_status=400,
                )
            template_name = sanitize_token(Path(body.template_path).name, field="template")
            # Template may be provided as absolute under templates root or relative name.
            if Path(body.template_path).is_absolute():
                template = resolve_under(templates_root, Path(body.template_path).name, field="template")
            else:
                template = resolve_under(templates_root, body.template_path, field="template")
            if template_name != record.label.template and record.label.template not in str(template):
                # Prefer explicit request path but keep product template reference auditable.
                log_event(
                    operation="illustrator.generate",
                    status="template_mismatch_warning",
                    request_template=template_name,
                    product_template=record.label.template,
                )
            if not template.is_file() and not body.dry_run:
                # Also accept .ai referenced even if only a documented placeholder exists.
                raise LabelosException(
                    f"Template not found under templates root: {template}",
                    code="TEMPLATE_MISSING",
                    category=INPUT_ERROR,
                    http_status=404,
                )

            out_dir = output_root / record.product.sku / record.product.revision
            if body.output_dir:
                out_dir = resolve_under(output_root, body.output_dir, field="output_dir")
            out_dir.mkdir(parents=True, exist_ok=True)
            # Never overwrite an existing approved revision export folder contents blindly.
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            job_out = out_dir / stamp
            if job_out.exists():
                raise LabelosException(
                    "Generated output directory already exists",
                    code="OUTPUT_EXISTS",
                    category=ARTWORK_GENERATION_ERROR,
                    http_status=409,
                )
            job_out.mkdir(parents=True)

            variables = record.variable_map()
            payload = build_extendscript_payload(
                template=template if template.is_file() else templates_root / record.label.template,
                output_dir=job_out,
                variables=variables,
                export_formats=body.export_formats,
                barcode_value=record.codes.barcode,
                qr_value=record.codes.qr,
            )

            if body.dry_run:
                # Dry-run validates request + writes a deterministic SVG stand-in for CI.
                stand_in = job_out / f"{record.product.sku}.svg"
                width = record.label.width_mm + 2 * record.label.bleed_mm
                height = record.label.height_mm + 2 * record.label.bleed_mm
                copy_bits = [
                    variables.get("PRODUCT_NAME", record.product.name),
                    variables.get("NET_WEIGHT", ""),
                ]
                text = " ".join(bit for bit in copy_bits if bit)
                stand_in.write_text(
                    (
                        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}mm" height="{height}mm" '
                        f'viewBox="0 0 {width} {height}">'
                        f'<text x="12" y="20" font-size="4">{text}</text></svg>\n'
                    ),
                    encoding="utf-8",
                )
                (job_out / "generation-request.json").write_text(
                    json.dumps(payload, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                result = {
                    "success": True,
                    "mode": "dry_run",
                    "outputs": [
                        {
                            "file": stand_in.name,
                            "path": str(stand_in),
                            "sha256": sha256_file(stand_in),
                            "bytes": stand_in.stat().st_size,
                            "format": "svg",
                        }
                    ],
                    "message": (
                        "Dry-run only. Illustrator was not invoked. "
                        "Deploy this bridge on an Illustrator workstation for live generation."
                    ),
                }
                return {
                    "success": True,
                    "status": "ARTWORK_GENERATED_DRY_RUN",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "result": result,
                }

            # Copy template into job folder for audit before Illustrator mutates a working copy.
            working_template = job_out / template.name
            shutil.copy2(template, working_template)
            payload["templatePath"] = str(working_template)
            result = run_illustrator_job(payload)
            if not result.get("outputs"):
                raise LabelosException(
                    "Illustrator reported success but returned zero outputs",
                    code="NO_OUTPUTS",
                    category=ARTWORK_GENERATION_ERROR,
                    http_status=500,
                )
            return {
                "success": True,
                "status": "ARTWORK_GENERATED",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "result": result,
            }

    return app


app = create_bridge_app()


def main() -> None:
    import uvicorn

    _bridge_token()
    host = os.environ.get("LABELOS_BRIDGE_HOST", "127.0.0.1")
    port = int(os.environ.get("LABELOS_BRIDGE_PORT", "8090"))
    uvicorn.run("illustrator_bridge.server:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
