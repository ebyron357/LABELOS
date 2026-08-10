# Production readiness status

## Implemented

- JSON label specification validation with physical dimensions, bleed, enforced safe-area
  content bounds, minimum DPI, and required-copy fields.
- SVG, PNG, and PDF artwork validation through bundled PyMuPDF.
- QR/barcode expected-value validation through bundled ZXing-C++; SVG and PDF artwork are
  rasterized at 300 DPI before decoding, and a decoder load failure is a validation error
  whenever code validation is requested.
- Operator CLI: validate, package, verify-package, and doctor.
- Immutable-style release directories containing copied artwork, validation report, manifest,
  and SHA-256 checksums.
- Committed passing and failing SVG regression fixtures for safe-area, dimensions, and
  required-copy checks, exercised through both unit tests and the operator CLI in CI.

## Known external/human blockers

- **TOOL UNAVAILABLE/BLOCKED:** Callas pdfToolbox is not installed or configured. No Callas
  preflight/profile result is claimed.
- No approved production artwork, regulatory-copy source, printer ICC/color target, or
  prepress acceptance profile is in this repository. The software can validate supplied
  specifications, but cannot certify these absent requirements.

## Next operator steps

1. Add approved product specifications and artwork fixtures for every SKU using the committed
   fixture configurations as a template.
2. Add the licensed Callas adapter/profile when the printer supplies its preflight target.
3. Run the full verification commands recorded below for each release.

## Verification record

Verified on 2026-08-10 from commit `f4cead2`:

```text
python3 -m pytest -q                      # 17 passed
python3 -m ruff check .                   # passed
python3 -m build --outdir /tmp/labelos-fixtures-build # sdist and wheel created
python3 -m labelos.cli validate examples/fixture-pass.json --json
! python3 -m labelos.cli validate examples/fixture-fail-safe-area.json --json
! python3 -m labelos.cli validate examples/fixture-fail-dimensions.json --json
! python3 -m labelos.cli validate examples/fixture-fail-missing-copy.json --json
```

Results: 17 tests passed; Ruff passed; the sdist and wheel were generated in
`/tmp/labelos-fixtures-build`; the passing fixture validated, and each failing fixture returned
the expected validation error. `doctor` previously confirmed PyMuPDF and ZXing-C++ are
available; Callas pdfToolbox remains unavailable.
QR and Code 128 regression tests generate raster, SVG, and PDF fixtures and verify their
decoded expected values. GitHub Actions runs tests, lint, and builds on Python 3.10 and 3.12.
