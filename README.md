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

### Native Illustrator build evidence

An Illustrator builder (for example `BravoPaws_Bacon_Tincture_Build.jsx`) that emits proof
artifacts can be gated by adding an optional `native_evidence` block to the configuration:

```json
{
  "native_evidence": {
    "evidence_json": "proof/BT-1000-30ML.evidence.json",
    "log": "proof/BT-1000-30ML.log",
    "preview_png": "proof/BT-1000-30ML.png",
    "native_artwork": "proof/BT-1000-30ML.ai",
    "required_layers": ["DIELINE", "BLEED", "SAFE_AREA", "BACKGROUND", "BRAND", "COPY", "REGULATORY", "BARCODE", "QR", "VARNISH"],
    "required_objects": ["BT-1000-30ML_QR", "BT-1000-30ML_BARCODE"]
  }
}
```

The evidence JSON must be an object containing `missing_layers` (empty), `layers` covering
every `required_layers` entry, `objects` covering every `required_objects` entry, and
`reopened_without_repair: true`. The log must end with `PASSED`, and all four artifacts must
exist. Any failure is a validation error, so packaging is refused. Packaging copies the four
artifacts into `native-evidence/` with SHA-256 entries in the manifest, and
`verify-package` re-checks them.

LABELOS records the evidence, it does not produce it: the artifacts must come from a real
Illustrator run on an operator workstation.

## Commands

- `labelos validate CONFIG [--json]`: validate format, dimensions, raster resolution,
  required copy, and configured barcode/QR values.
- `labelos package CONFIG DESTINATION`: validates, then writes artwork, a JSON validation
  report, and a SHA-256 manifest. Existing package destinations are never overwritten.
- `labelos verify-package DESTINATION`: verifies package checksums.
- `labelos doctor`: reports optional validator availability. Callas pdfToolbox is explicitly
  reported as unavailable until a real adapter and licensed profile are configured.

## Current scope and limitations

The core validator provides reproducible local checks and package integrity. Commercial
prepress profiles, approved regulatory copy, brand artwork, printer-specific color targets,
and a Callas adapter are not present in this repository; they must be supplied and approved
by the appropriate owner before a particular label can be certified for print.

Every package manifest lists `blocked_requirements`: `printer_profile`, `icc_profile`,
`regulatory_approval`, and `production_pdf`. LABELOS never generates PDF/X-1a output and a
passing native-evidence gate does not clear any of those blockers.
