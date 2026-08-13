"""Production dependency diagnostics for ``labelos doctor`` and ``GET /doctor``.

Every component reports one of the following states and nothing else:

``ready``
    Verified working in this environment right now.
``configured``
    Configuration is present but the dependency itself could not be verified here.
``missing``
    Required configuration or component is absent.
``unavailable``
    Configured but not reachable/installed on this machine.
``unhealthy``
    Present but returning errors.

``ready`` is never reported for a dependency that has not actually been verified.
"""

from __future__ import annotations

import os
import platform
import sys
from pathlib import Path
from typing import Any

from . import __version__
from .preflight import (
    NOT_CONFIGURED,
    PASS,
    PdfToolboxAdapter,
    load_config,
)

READY = "ready"
CONFIGURED = "configured"
MISSING = "missing"
UNAVAILABLE = "unavailable"
UNHEALTHY = "unhealthy"

VALID_STATES = frozenset({READY, CONFIGURED, MISSING, UNAVAILABLE, UNHEALTHY})

#: States that mean the component cannot serve a production run.
BLOCKING_STATES = frozenset({MISSING, UNAVAILABLE, UNHEALTHY})


def _component(state: str, detail: str, **extra: Any) -> dict[str, Any]:
    return {"state": state, "detail": detail, **extra}


def _python_module(name: str, module: str) -> dict[str, Any]:
    try:
        __import__(module)
    except ImportError:
        return _component(MISSING, f"install Python module {module}", component=name)
    return _component(READY, f"{module} imported successfully", component=name)


def _core() -> dict[str, Any]:
    return _component(READY, f"LABELOS {__version__} importable", version=__version__)


def _python_environment() -> dict[str, Any]:
    version = platform.python_version()
    minimum = (3, 10)
    if sys.version_info[:2] < minimum:
        return _component(
            UNHEALTHY,
            f"Python {version} is below the required 3.10",
            python=version,
        )
    return _component(READY, f"Python {version}", python=version)


def _storage() -> dict[str, Any]:
    configured = os.environ.get("LABELOS_STORAGE_PATH", "").strip()
    root = Path(configured or "storage").expanduser()
    if not configured:
        detail = "LABELOS_STORAGE_PATH is unset; using non-persistent default './storage'"
        state = CONFIGURED if root.is_dir() else MISSING
        return _component(state, detail, path=str(root.resolve()))
    if not root.exists():
        return _component(MISSING, f"storage path does not exist: {root}", path=str(root))
    if not root.is_dir():
        return _component(UNHEALTHY, f"storage path is not a directory: {root}", path=str(root))
    if not os.access(root, os.W_OK):
        return _component(UNHEALTHY, f"storage path is not writable: {root}", path=str(root))
    return _component(READY, f"writable storage at {root}", path=str(root.resolve()))


def _api() -> dict[str, Any]:
    token = os.environ.get("LABELOS_API_TOKEN", "").strip()
    base_url = os.environ.get("LABELOS_API_BASE_URL", "").strip()
    if not token:
        return _component(MISSING, "LABELOS_API_TOKEN is not set; the API refuses to serve")
    if len(token) < 16:
        return _component(UNHEALTHY, "LABELOS_API_TOKEN is shorter than 16 characters")
    if not base_url:
        return _component(CONFIGURED, "API token configured; LABELOS_API_BASE_URL is unset")
    return _component(
        CONFIGURED,
        "API token and base URL configured; liveness is proven by /health and /ready",
        base_url=base_url,
    )


def _illustrator_bridge() -> dict[str, Any]:
    url = os.environ.get("LABELOS_BRIDGE_URL", "").strip()
    templates = os.environ.get("LABELOS_TEMPLATES_PATH", "").strip()
    if not url:
        return _component(MISSING, "LABELOS_BRIDGE_URL is not set")
    if not templates:
        return _component(CONFIGURED, "bridge URL configured; LABELOS_TEMPLATES_PATH is unset", url=url)
    if not Path(templates).expanduser().is_dir():
        return _component(UNAVAILABLE, f"templates path does not exist: {templates}", url=url)
    return _component(CONFIGURED, "bridge URL and templates path configured", url=url)


def _illustrator() -> dict[str, Any]:
    template = os.environ.get("LABELOS_ILLUSTRATOR_TEMPLATE", "").strip()
    if platform.system() != "Windows":
        return _component(
            UNAVAILABLE,
            "Adobe Illustrator automation requires a licensed Windows workstation; "
            f"this host is {platform.system()}",
        )
    if not template:
        return _component(MISSING, "LABELOS_ILLUSTRATOR_TEMPLATE (approved .ai master) is not set")
    if not Path(template).expanduser().is_file():
        return _component(UNAVAILABLE, f"approved .ai template not found: {template}")
    return _component(CONFIGURED, "approved .ai template configured on a Windows host")


def _pdftoolbox() -> dict[str, Any]:
    config = load_config()
    if not config.executable:
        return _component(MISSING, "LABELOS_PDFTOOLBOX_PATH is not set")
    if not config.profile:
        return _component(MISSING, "LABELOS_PDFTOOLBOX_PROFILE is not set")
    result = PdfToolboxAdapter(config=config).version()
    if result.status == NOT_CONFIGURED:
        return _component(UNAVAILABLE, result.message, executable=config.executable)
    if result.status != PASS:
        return _component(UNHEALTHY, result.message, executable=config.executable)
    if not Path(config.profile).expanduser().is_file():
        return _component(
            UNHEALTHY,
            f"pdfToolbox CLI responded but the profile is missing: {config.profile}",
            executable=config.executable,
        )
    return _component(READY, result.message, executable=config.executable, profile=config.profile)


def _directory_component(env_name: str, label: str) -> dict[str, Any]:
    configured = os.environ.get(env_name, "").strip()
    if not configured:
        return _component(MISSING, f"{env_name} is not set; no approved {label} available")
    path = Path(configured).expanduser()
    if not path.exists():
        return _component(UNAVAILABLE, f"{label} path does not exist: {path}")
    if path.is_dir() and not any(path.iterdir()):
        return _component(MISSING, f"{label} path is empty: {path}")
    return _component(CONFIGURED, f"{label} present at {path}", path=str(path))


def _n8n() -> dict[str, Any]:
    workflow = os.environ.get("LABELOS_N8N_WORKFLOW_ID", "").strip()
    base_url = os.environ.get("LABELOS_API_BASE_URL", "").strip()
    if not workflow:
        return _component(MISSING, "LABELOS_N8N_WORKFLOW_ID is not set")
    if not base_url:
        return _component(MISSING, "LABELOS_API_BASE_URL is required for n8n HTTP nodes")
    return _component(
        CONFIGURED,
        "n8n workflow id and LABELOS base URL configured; live execution proves readiness",
        workflow_id=workflow,
        base_url=base_url,
    )


def _production_config() -> dict[str, Any]:
    required = ("LABELOS_API_TOKEN", "LABELOS_STORAGE_PATH", "LABELOS_API_BASE_URL")
    absent = [name for name in required if not os.environ.get(name, "").strip()]
    if absent:
        return _component(MISSING, "unset production variables: " + ", ".join(absent), missing=absent)
    return _component(CONFIGURED, "core production environment variables are set")


def run_doctor() -> dict[str, Any]:
    """Return the full production dependency report."""
    components: dict[str, dict[str, Any]] = {
        "labelos_core": _core(),
        "python_environment": _python_environment(),
        "storage": _storage(),
        "api": _api(),
        "illustrator_bridge": _illustrator_bridge(),
        "adobe_illustrator": _illustrator(),
        "pdftoolbox": _pdftoolbox(),
        "n8n": _n8n(),
        "printer_profiles": _directory_component("LABELOS_PRINTER_PROFILES_PATH", "printer profiles"),
        "product_schemas": _directory_component("LABELOS_PRODUCT_DATA_PATH", "approved product data"),
        "production_config": _production_config(),
        "pdf_inspection": _python_module("PyMuPDF", "pymupdf"),
        "code_decoder": _python_module("ZXing-C++", "zxingcpp"),
    }
    blocking = sorted(
        name for name, entry in components.items() if entry["state"] in BLOCKING_STATES
    )
    return {
        "passed": not blocking,
        "components": components,
        # Backwards-compatible view for existing API/n8n consumers.
        "tools": {
            name: {"available": entry["state"] == READY, "status": entry["state"], "detail": entry["detail"]}
            for name, entry in components.items()
        },
        "blocking": blocking,
        "production_ready": not blocking,
    }
