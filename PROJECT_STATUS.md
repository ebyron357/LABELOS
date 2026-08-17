# Production readiness status

## Implemented

- JSON label specification validation with physical dimensions, bleed, safe-area sanity,
  minimum DPI, and required-copy fields.
- SVG, PNG, and PDF artwork validation through bundled PyMuPDF.
- Effective-DPI enforcement for data-URI raster images embedded in SVG artwork, including
  placed-size metadata and fail-closed errors when inspection cannot complete.
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

Verified on 2026-08-17 from commit `PENDING`:

```text
python3 -m pytest -q
python3 -m ruff check .
python3 -m compileall -q labelos tests
python3 -m build --outdir /tmp/labelos-final-build
python3 -m labelos.cli validate examples/label.json --json
python3 -m labelos.cli package examples/label.json /tmp/labelos-final-e2e --json
python3 -m labelos.cli verify-package /tmp/labelos-final-e2e --json
python3 -m labelos.cli doctor --json
```

Results: 10 tests passed; Ruff and compilation passed; the sdist and wheel were generated in
`/tmp/labelos-final-build`; and the end-to-end package was created and checksum-verified at
`/tmp/labelos-final-e2e`. `doctor` confirmed PyMuPDF and ZXing-C++ are available; Callas
pdfToolbox remains unavailable. QR and Code 128 regression tests generate raster, SVG, and PDF
fixtures and verify their decoded expected values; SVG tests cover both passing and failing
effective-DPI checks for data-URI raster images. GitHub Actions runs tests, lint, and builds on
Python 3.10 and 3.12.
