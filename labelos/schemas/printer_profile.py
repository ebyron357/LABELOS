"""Printer profile model. Rules must come from approved printer specifications."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class PrinterProfile(BaseModel):
    """
    Printer-facing production constraints.

    Do not invent numeric limits. Populate only from approved printer specs.
    Unspecified fields remain null and are not enforced.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    vendor: str | None = None
    source_document: str | None = Field(
        default=None,
        description="Reference to the approved printer specification document",
    )
    approved: bool = False
    page_width_mm: float | None = None
    page_height_mm: float | None = None
    bleed_mm: float | None = None
    safe_area_mm: float | None = None
    color_space: str | None = None
    icc_profile: str | None = None
    pdf_standard: str | None = None
    min_font_size_pt: float | None = None
    min_line_weight_pt: float | None = None
    black_construction: str | None = None
    overprint_rules: str | None = None
    barcode_requirements: dict[str, Any] | None = None
    ink_limit_percent: float | None = None
    dieline_requirements: str | None = None
    notes: str | None = None

    def enforceable(self) -> bool:
        """Profiles without approval must never silently enforce invented limits."""
        return self.approved and self.source_document is not None
