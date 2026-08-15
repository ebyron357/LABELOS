# LABELOS

LABELOS validates packaging-label artwork before it is released to production and creates
checksummed release packages. It deliberately fails closed: an unavailable required decoder
or an invalid artwork check prevents packaging.

## Quick start

```bash
python -m pip install -e .
labelos validate examples/label.json
labelos package examples/label.json dist/example-label
labelos verify-package dist/example-label
labelos doctor
```

The configuration is JSON:

```json
{
  "artwork": "label.pdf",
  "width_mm": 100,
  "height_mm": 50,
  "bleed_mm": 3,
  "safe_area_mm": 2,
  "min_dpi": 300,
  "required_copy": ["Product name", "NET 250 g"],
  "barcode_value": "0123456789012",
  "qr_value": "https://example.com/product"
}
```

Artwork dimensions include bleed: the example above expects a 106 × 56 mm asset. SVG, PNG,
and PDF artwork are accepted. PDF inspection and QR/barcode decoding are installed with
LABELOS; SVG and PDF are rendered at 300 DPI before code decoding. If `barcode_value` or
`qr_value` is configured but the decoder cannot load, validation fails rather than asserting a
code was checked.

When `safe_area_mm` is configured, visible non-background marks must be inset from the outer
artwork edge by `bleed_mm + safe_area_mm`. SVG and PDF artwork are rendered at 300 DPI for this
check. A uniform canvas color sampled from all four corners is treated as full-bleed background;
otherwise the artwork is assessed conservatively.

## Commands

- `labelos validate CONFIG [--json]`: validate format, dimensions, raster resolution,
  required copy, safe-area bounds, and configured barcode/QR values.
- `labelos package CONFIG DESTINATION`: validates, then writes artwork, a JSON validation
  report, canonical `label-spec.json`, and a SHA-256/byte-count manifest. Existing package
  destinations are never overwritten.
- `labelos verify-package DESTINATION`: verifies manifest schema, checksums, byte counts,
  regular-file paths, passing validation status, and packaged report/spec consistency.
- `labelos doctor`: reports optional validator availability. Callas pdfToolbox is explicitly
  reported as unavailable until a real adapter and licensed profile are configured.

## Current scope and limitations

The core validator provides reproducible local checks and package integrity. Commercial
prepress profiles, approved regulatory copy, brand artwork, printer-specific color targets,
and a Callas adapter are not present in this repository; they must be supplied and approved
by the appropriate owner before a particular label can be certified for print.
