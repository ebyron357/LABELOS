# LABELOS

LABELOS is a **validation and release engine** for packaging-label artwork.

An operator uses it today as a command-line tool: validate artwork against a label
spec, read a structured report, then create and verify a checksummed release package.

It does **not** generate artwork, edit labels, or replace a licensed prepress system.

## Install

Python 3.10 or newer is required.

```bash
python -m pip install -e ".[test,dev]"
labelos doctor --json
```

`doctor` must show Pillow, PyMuPDF, and ZXing-C++ as available. Callas pdfToolbox is
reported as `SKIPPED_NOT_CONFIGURED` until a real licensed adapter exists. That is
expected. Do not treat it as a pass.

## Operator workflow

1. **Install** LABELOS as above.
2. **Prepare artwork** as SVG, PNG, or single-page PDF. Artwork size must include bleed.
3. **Create a label spec** JSON file. Start from [`examples/label.json`](examples/label.json).
4. **Validate:** `labelos validate examples/label.json --json`
5. **Interpret errors.** Each issue has a `code` and `message`. See [Error codes](#error-codes).
6. **Fix the artwork or spec.** Do not package a failing report.
7. **Validate again** until the report shows `"passed": true`.
8. **Package:** `labelos package examples/label.json releases/sku-revision`
9. **Verify the package:** `labelos verify-package releases/sku-revision`
10. **Release** only the verified package directory. Keep the artwork, `validation-report.json`,
    `label-spec.json`, and `manifest.json` together. Do not edit files after packaging.

## Minimal working example

The bundled example is a 100 × 50 mm trim label with 3 mm bleed (artwork 106 × 56 mm):

```bash
labelos validate examples/label.json --json
labelos package examples/label.json storage/demo-release
labelos verify-package storage/demo-release
```

A known failing spec is [`examples/failing-label.json`](examples/failing-label.json)
(`REQUIRED_COPY_MISSING`). Use it to see how errors look:

```bash
labelos validate examples/failing-label.json --json
```

### Label spec fields

```json
{
  "artwork": "path/to/artwork.svg",
  "width_mm": 100,
  "height_mm": 50,
  "trim_mm": 0,
  "bleed_mm": 3,
  "safe_area_mm": 2,
  "min_dpi": 300,
  "required_copy": ["Example Product", "NET 250 g"],
  "barcode_value": null,
  "qr_value": null
}
```

`width_mm` / `height_mm` are the **trim** size. Artwork file dimensions must equal
trim plus bleed on all sides. Set `barcode_value` and/or `qr_value` only when those
codes must decode to an expected string.

## Commands

| Command | Purpose |
| --- | --- |
| `labelos validate CONFIG [--json]` | Validate artwork and print a report |
| `labelos package CONFIG DESTINATION [--json]` | Validate, then write a release package |
| `labelos verify-package DESTINATION [--json]` | Check package checksums, paths, and passing status |
| `labelos doctor [--json]` | Report required and optional tools |

`package` refuses to write over an existing destination and refuses failed reports.
`verify-package` rejects path traversal, non-regular files, checksum mismatches,
byte-count mismatches, and reports that do not record a pass. Local raster files linked
from SVG artwork are DPI-checked and included in the release package.

## Error codes

| Code | Meaning |
| --- | --- |
| `ARTWORK_MISSING` | Artwork path does not exist |
| `FORMAT_UNSUPPORTED` | Not SVG, PNG, or PDF |
| `SVG_INVALID` / `PNG_INVALID` / `PDF_INVALID` | File is malformed; validation failed closed |
| `SVG_UNSAFE_XML` | SVG declares a DOCTYPE/entity; flatten the file so copy is literal text |
| `PNG_READER_UNAVAILABLE` | Pillow is missing, so PNG image data cannot be inspected |
| `SVG_DIMENSIONS_MISSING` | SVG width/height must use mm, cm, in, or pt |
| `DIMENSIONS_MISMATCH` | Artwork size is not trim + bleed |
| `DPI_TOO_LOW` | Raster file effective resolution is below `min_dpi` |
| `SVG_EMBEDDED_IMAGE_DPI_TOO_LOW` | Placed SVG raster is below `min_dpi` |
| `SVG_EMBEDDED_IMAGE_INSPECTION_FAILED` | A placed SVG image is missing, unsafe, or unreadable |
| `PDF_IMAGE_DPI_TOO_LOW` | Placed PDF raster is below `min_dpi` |
| `SAFE_AREA_VIOLATION` | Visible content extends outside trim + safe inset |
| `REQUIRED_COPY_MISSING` | A required string was not found in the artwork |
| `CODE_VALUE_MISMATCH` | QR/barcode did not decode to the expected value |
| `DECODER_UNAVAILABLE` | Pillow or zxing-cpp is missing while a code was requested |

## Capabilities

See [PROJECT_STATUS.md](PROJECT_STATUS.md) for **AVAILABLE NOW**, **PARTIAL**,
**EXTERNAL DEPENDENCY**, and **FUTURE**. Commercial Callas/pdfToolbox preflight is
**not available**.

## Documentation

| Topic | Doc |
| --- | --- |
| Status and capability truth | [PROJECT_STATUS.md](PROJECT_STATUS.md) |
| Architecture | [docs/architecture.md](docs/architecture.md) |
| Local development | [docs/local-development.md](docs/local-development.md) |
| HTTP API (future / optional) | [docs/api.md](docs/api.md) |
| Troubleshooting | [docs/troubleshooting.md](docs/troubleshooting.md) |
