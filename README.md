# LABELOS

LABELOS is a local, auditable label-production gate. It validates raster artwork and
single-page PDFs against an explicit JSON specification, decodes barcode and QR
content, and creates checksummed delivery packages only after validation succeeds.

## Install

```bash
python -m pip install -e '.[test]'
```

## Operator workflow

Create a specification:

```json
{
  "width_mm": 50,
  "height_mm": 30,
  "bleed_mm": 0,
  "safe_area_mm": 2,
  "minimum_dpi": 300,
  "required_copy": ["NET CONTENTS 12 OZ"],
  "barcode": {"value": "123456789012", "format": "Code128"},
  "qr": {"value": "https://example.com/label", "format": "QRCode"}
}
```

Then run:

```bash
labelos doctor
labelos validate-image label.png --spec label-spec.json
labelos export label.png --spec label-spec.json --destination production-label.pdf
labelos validate-pdf production-label.pdf --spec label-spec.json
labelos package production-label.pdf --spec label-spec.json --destination delivery/
```

`export` places raster artwork on a single PDF page at the specified finished size.
`validate-*` exits with 0 on success, 2 for validation failures, and 1 for invalid
input or operational errors. `package` writes `validation-report.json`, the original
PDF, and `manifest.json` with a SHA-256 checksum.

## Validation coverage and limits

- Raster validation checks embedded DPI, physical dimensions, optional color mode, and
  decodes QR and linear barcode values with ZXing-C++.
- PDF validation checks one-page geometry, extractable required copy, and decodes
  symbols from a 300-DPI (or specification DPI) rendering.
- Required-copy validation is reliable for PDF text objects. Raster artwork does not
  run OCR; machine-readable symbol text is the only raster text evidence.
- Trim, bleed, and safe-area values are recorded in the specification. Output
  dimensions include bleed. Geometric inspection of visual safe-area content requires
  artwork-specific layout semantics and is intentionally not claimed.
- Callas pdfToolbox, font embedding, ICC/output-intent, ink coverage, and trapping
  checks are not bundled. `doctor` explicitly reports pdfToolbox as
  `TOOL UNAVAILABLE/BLOCKED` until a real adapter is configured.

## Development verification

```bash
python -m pytest
python -m ruff check .
python -m build
```
