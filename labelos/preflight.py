"""Optional commercial prepress adapter (Callas pdfToolbox)."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Protocol


@dataclass
class PreflightResult:
    enabled: bool
    status: str
    profile: str | None = None
    message: str = ""
    details: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if payload["details"] is None:
            del payload["details"]
        return payload


class PreflightAdapter(Protocol):
    def run(self, artwork_path: str, profile: str | None = None) -> PreflightResult: ...


class DisabledCallasAdapter:
    """
    Default adapter until Callas is licensed, installed, and profiled.

    Never fakes a pass. Reports explicitly that commercial preflight is unavailable.
    """

    def run(self, artwork_path: str, profile: str | None = None) -> PreflightResult:
        return PreflightResult(
            enabled=False,
            status="SKIPPED_NOT_CONFIGURED",
            profile=profile,
            message=(
                "Callas pdfToolbox is not licensed/configured. "
                "Commercial preflight was not executed."
            ),
            details={"artwork": artwork_path},
        )


def get_preflight_adapter() -> PreflightAdapter:
    """Factory hook for future Callas integration without redesign."""
    return DisabledCallasAdapter()
