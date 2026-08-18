"""n8n workflow artifact smoke tests."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW_PATH = ROOT / "n8n" / "labelos-label-validation-release.n8n.json"


def test_n8n_workflow_calls_real_labelos_routes():
    workflow = json.loads(WORKFLOW_PATH.read_text(encoding="utf-8"))
    assert workflow["id"] == "6CwUVmFDLQbzdNBd"
    assert workflow["active"] is False
    names = {node["name"] for node in workflow["nodes"]}
    assert {
        "LABELOS Doctor",
        "LABELOS Validate",
        "LABELOS Package",
        "LABELOS Verify Package",
    } <= names
    raw = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "LABELOS_API_BASE_URL" in raw
    assert "/doctor" in raw
    assert "/validate" in raw
    assert "/package" in raw
    assert "/verify-package" in raw
