"""Deployment configuration regression tests."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_render_blueprint_and_deployment_guide_target_canonical_main_branch():
    """A Blueprint deploy must use the same branch as the validated release engine."""
    blueprint = (ROOT / "render.yaml").read_text(encoding="utf-8")
    guide = (ROOT / "docs" / "deployment.md").read_text(encoding="utf-8")

    assert "branch: main" in blueprint
    assert "branch **`main`**" in guide
    assert "feat/production-label-automation" not in blueprint
    assert "feat/production-label-automation" not in guide
