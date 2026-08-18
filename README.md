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
and PDF artwork are accepted. A nonzero `safe_area_mm` checks visible artwork against the
trim-safe bounds; SVG and PDF are rendered at 300 DPI for this check. PNG resolution is
validated from its pixels, and every placed raster image in a PDF is checked at its effective
placement DPI. SVG and PDF are also rendered at 300 DPI before barcode/QR decoding. If
`barcode_value` or `qr_value` is configured but the decoder cannot load, validation fails
rather than asserting a code was checked.

## Commands

- `labelos validate CONFIG [--json]`: validate format, dimensions, trim-safe area, raster
  resolution, required copy, and configured barcode/QR values.
- `labelos package CONFIG DESTINATION`: validates, then writes artwork, the resolved JSON
  specification, a JSON validation report, and a SHA-256 manifest. Existing package
  destinations are never overwritten.
- `labelos verify-package DESTINATION`: verifies manifest structure, safe package filenames,
  regular files, byte counts, checksums, and report/spec/artwork consistency.
- `labelos doctor`: reports optional validator availability. Callas pdfToolbox is explicitly
  reported as unavailable until a real adapter and licensed profile are configured.

## Current scope and limitations

The core validator provides reproducible local checks and package integrity. Commercial
prepress profiles, approved regulatory copy, brand artwork, printer-specific color targets,
and a Callas adapter are not present in this repository; they must be supplied and approved
by the appropriate owner before a particular label can be certified for print.
