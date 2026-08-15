# Production readiness status

## Implemented

- JSON label specification validation with physical dimensions, bleed, enforced rasterized
  safe-area checks, minimum DPI, and required-copy fields.
- SVG, PNG, and PDF artwork validation through bundled PyMuPDF.
- QR/barcode expected-value validation through bundled ZXing-C++; SVG and PDF artwork are
  rasterized at 300 DPI before decoding, and a decoder load failure is a validation error
  whenever code validation is requested.
- Operator CLI: validate, package, verify-package, and doctor.
- Immutable-style release directories containing copied artwork, validation report, schema-v2
  manifest, SHA-256 checksums, and byte counts. Verification rejects unsafe manifest paths,
  report/spec inconsistencies, and unexpected artifacts.
- Passing and failing fixture coverage plus CLI/package and safe-area regression tests for SVG,
  PNG, and PDF.

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

Verified on 2026-08-15 from commit `0eda7acd22869b4b6de2d64e715e6efe39ada5c5`:

```text
python3 -m pytest -q                      # 13 passed
python3 -m ruff check .                   # passed
python3 -m compileall -q labelos tests    # passed
python3 -m build                          # sdist and wheel created in dist/
python3 -m labelos.cli validate examples/label.json --json
python3 -m labelos.cli package examples/label.json /tmp/labelos-e2e-v2 --json
python3 -m labelos.cli verify-package /tmp/labelos-e2e-v2 --json
python3 -m labelos.cli doctor --json
```

Results: 13 tests passed; Ruff and compilation passed; the sdist and wheel were generated in
`dist/`; and the end-to-end package was created and verified at `/tmp/labelos-e2e-v2`.
`doctor` confirmed PyMuPDF and ZXing-C++ are available; Callas pdfToolbox remains unavailable.
QR and Code 128 regression tests generate raster, SVG, and PDF fixtures and verify their decoded
expected values. Safe-area regressions cover a uniform SVG full bleed plus PNG and PDF margin
violations. GitHub Actions runs tests, lint, and builds on Python 3.10 and 3.12.
