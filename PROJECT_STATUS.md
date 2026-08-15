# Production readiness status

## Implemented

- JSON label specification validation with physical dimensions, bleed, safe-area configuration,
  minimum DPI, and required-copy fields.
- SVG, PNG, and PDF artwork validation through bundled PyMuPDF.
- Safe-area artwork enforcement for SVG, PNG, and PDF. LABELOS rasterizes the artwork, permits
  a uniform full-bleed background, and fails validation if foreground extends outside the trim
  inset plus configured safe area.
- QR/barcode expected-value validation through bundled ZXing-C++; SVG and PDF artwork are
  rasterized at 300 DPI before decoding, and a decoder load failure is a validation error
  whenever code validation is requested.
- Operator CLI: validate, package, verify-package, and doctor.
- Immutable-style release directories containing copied artwork, validation report, manifest,
  and SHA-256 checksums.
- Passing and failing fixture coverage plus CLI/package regression tests.

## Known external/human blockers

- **TOOL UNAVAILABLE/BLOCKED:** Callas pdfToolbox is not installed or configured. No Callas
  preflight/profile result is claimed.
- No approved production artwork, regulatory-copy source, printer ICC/color target, or
  prepress acceptance profile is in this repository. The software can validate supplied
  specifications, but cannot certify these absent requirements.

## Next operator steps

1. Add approved product specs and both passing/failing artwork fixtures for every SKU.
2. Add the licensed Callas adapter/profile when the printer supplies its preflight target.
3. Run the full verification commands recorded below for each release.

## Verification record

Verified on 2026-08-15 from commit `55d83c7a729b5824a2e0cd081a90076cb5c5b726`:

```text
python3 -m pytest                         # 13 passed
python3 -m ruff check .                   # passed
python3 -m build                          # sdist and wheel created in dist/
python3 -m labelos.cli validate examples/label.json --json
python3 -m labelos.cli package examples/label.json /tmp/labelos-e2e --json
python3 -m labelos.cli verify-package /tmp/labelos-e2e --json
python3 -m labelos.cli doctor --json
```

Results: 13 tests passed; Ruff passed; the sdist and wheel were generated in `dist/`; and the
end-to-end package was created and checksum-verified at `/tmp/labelos-e2e`.
`doctor` confirmed PyMuPDF and ZXing-C++ are available; Callas pdfToolbox remains unavailable.
QR and Code 128 regression tests generate raster, SVG, and PDF fixtures and verify their
decoded expected values. Safe-area regression tests cover passing full-bleed raster and SVG
artwork plus a failing raster foreground intrusion. Invalid PDF input is reported as
`PDF_INVALID` instead of crashing the CLI. GitHub Actions runs tests, lint, and builds on
Python 3.10 and 3.12.
