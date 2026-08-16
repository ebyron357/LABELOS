# Production readiness status

## Implemented

- JSON label specification validation with physical dimensions, bleed, safe-area sanity,
  minimum DPI, and required-copy fields.
- SVG, PNG, and PDF artwork validation through bundled PyMuPDF.
- QR/barcode expected-value validation through bundled ZXing-C++; SVG and PDF artwork are
  rasterized at 300 DPI before decoding, and a decoder load failure is a validation error
  whenever code validation is requested.
- Operator CLI: validate, package, verify-package, and doctor.
- Immutable-style release directories containing copied artwork, validation report, manifest,
  and SHA-256 checksums. Package verification rejects unsafe manifest paths, symlinks, byte-count
  or checksum mismatches, non-passing/inconsistent reports, and unexpected package files.
- Malformed PDFs fail closed with `PDF_INVALID` rather than terminating the CLI.
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

Verified on 2026-08-16 for release-verification commit
`efa75449687f30f84311bf8fd59471976f113714`:

```text
python3 -m pytest -q                      # 13 passed
python3 -m ruff check .                   # passed
python3 -m compileall -q labelos          # passed
python3 -m pip check                      # no broken requirements
python3 -m build --outdir /tmp/labelos-e2e-JnBSHS/build
python3 -m labelos.cli validate examples/label.json --json
python3 -m labelos.cli package examples/label.json /tmp/labelos-e2e-JnBSHS/release --json
python3 -m labelos.cli verify-package /tmp/labelos-e2e-JnBSHS/release --json
python3 -m labelos.cli doctor --json
python3 -m labelos.cli validate /tmp/labelos-e2e-JnBSHS/corrupt.json --json  # exits 1, PDF_INVALID
```

Results: 13 tests passed; Ruff, compileall, and dependency checks passed; the sdist and wheel
were generated at `/tmp/labelos-e2e-JnBSHS/build`; and the end-to-end package was created and
schema/integrity-verified at `/tmp/labelos-e2e-JnBSHS/release`. The malformed-PDF CLI regression
returned the expected nonzero validation result without a traceback.
`doctor` confirmed PyMuPDF and ZXing-C++ are available; Callas pdfToolbox remains unavailable.
QR and Code 128 regression tests generate raster, SVG, and PDF fixtures and verify their
decoded expected values. GitHub Actions runs tests, lint, and builds on Python 3.10 and 3.12.
