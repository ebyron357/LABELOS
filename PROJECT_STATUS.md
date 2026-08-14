# Production readiness status

## Implemented

- JSON label specification validation with physical dimensions, bleed, safe-area configuration
  sanity, minimum DPI, and required-copy fields.
- SVG, PNG, and PDF artwork validation through bundled PyMuPDF.
- Malformed PDF artwork fails closed with a `PDF_INVALID` validation error rather than
  terminating the operator workflow.
- QR/barcode expected-value validation through bundled ZXing-C++; SVG and PDF artwork are
  rasterized at 300 DPI before decoding, and a decoder load failure is a validation error
  whenever code validation is requested.
- Operator CLI: validate, package, verify-package, and doctor.
- Immutable-style release directories containing copied artwork, validation report, manifest,
  and SHA-256 checksums.
- Passing fixture coverage plus CLI/package regression tests.

## Known release gates and external/human blockers

- **IMPLEMENTATION REQUIRED:** `safe_area_mm` currently validates only configuration sanity; no
  artwork-object bounds check is implemented. A passing report is not safe-area clearance.
- **IMPLEMENTATION REQUIRED:** Add committed reusable failing artwork fixtures for operator
  validation scenarios.

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

Verified on 2026-08-14 from commit `d4f4635d0319a7e2712b145e9affef60bcd36edf`:

```text
python3 -m pytest -q                      # 10 passed
python3 -m ruff check .                   # passed
python3 -m build --outdir /tmp/labelos-build-20260814
python3 -m labelos.cli validate examples/label.json --json
python3 -m labelos.cli package examples/label.json /tmp/labelos-e2e-20260814 --json
python3 -m labelos.cli verify-package /tmp/labelos-e2e-20260814 --json
python3 -m labelos.cli doctor --json
```

Results: 10 tests passed; Ruff passed; the sdist and wheel were generated in
`/tmp/labelos-build-20260814`; and the end-to-end package was created and checksum-verified at
`/tmp/labelos-e2e-20260814`. The malformed-PDF CLI regression test verified exit code 1 and a
machine-readable `PDF_INVALID` issue with no traceback.
`doctor` confirmed PyMuPDF and ZXing-C++ are available; Callas pdfToolbox remains unavailable.
QR and Code 128 regression tests generate raster, SVG, and PDF fixtures and verify their
decoded expected values. GitHub Actions runs tests, lint, and builds on Python 3.10 and 3.12.
