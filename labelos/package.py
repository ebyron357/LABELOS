"""Production package creation with checksums and validation evidence."""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

import pymupdf as fitz

from .models import LabelSpec
from .validator import validate_pdf


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def export_pdf(image_path: str | Path, spec: LabelSpec, destination: str | Path) -> Path:
    """Place raster artwork on a single PDF page at the specified finished size."""

    source = Path(image_path)
    output = Path(destination)
    if output.exists():
        raise ValueError(f"refusing to overwrite existing output: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    document = fitz.open()
    try:
        page = document.new_page(
            width=spec.finished_width_mm / 25.4 * 72,
            height=spec.finished_height_mm / 25.4 * 72,
        )
        page.insert_image(page.rect, filename=str(source))
        document.save(output)
    finally:
        document.close()
    return output


def create_package(
    pdf_path: str | Path, spec: LabelSpec, destination: str | Path
) -> dict[str, object]:
    """Validate a PDF and create an immutable-style delivery directory."""

    source = Path(pdf_path)
    output = Path(destination)
    if output.exists() and any(output.iterdir()):
        raise ValueError(f"package destination is not empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    result = validate_pdf(source, spec)
    report_path = output / "validation-report.json"
    report_path.write_text(json.dumps(result.to_dict(), indent=2) + "\n", encoding="utf-8")
    if not result.valid:
        raise ValueError(f"refusing to package failed artwork; see {report_path}")
    artwork_path = output / source.name
    shutil.copy2(source, artwork_path)
    manifest = {
        "schema_version": 1,
        "created_at": datetime.now(UTC).isoformat(),
        "artwork": {"file": artwork_path.name, "sha256": _sha256(artwork_path)},
        "specification": spec.to_dict(),
        "validation_report": report_path.name,
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest
