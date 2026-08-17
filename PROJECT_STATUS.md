# Production readiness status

## Implemented

- JSON label specification validation with physical dimensions, bleed, safe-area sanity,
  minimum DPI, and required-copy fields; extractable SVG/PDF text is checked against the
  bleed + safe-area inset.
- SVG, PNG, and PDF artwork validation through bundled PyMuPDF.
- QR/barcode expected-value validation through bundled ZXing-C++; SVG and PDF artwork are
  rasterized at 300 DPI before decoding, and a decoder load failure is a validation error
  whenever code validation is requested.
- Operator CLI: validate, package, verify-package, and doctor.
- Closed release directories containing copied artwork, validation report, and schema-v2
  SHA-256 manifests. Verification rejects malformed entries, mismatched byte counts/checksums,
  report/spec inconsistencies, symlinks, traversal paths, and untracked files.
- Passing and failing fixture coverage plus CLI/package regression tests.

## Known external/human blockers

- **TOOL UNAVAILABLE/BLOCKED:** Callas pdfToolbox is not installed or configured. No Callas
  preflight/profile result is claimed.
- No approved production artwork, regulatory-copy source, printer ICC/color target, or
  prepress acceptance profile is in this repository. The software can validate supplied
  specifications, but cannot certify these absent requirements.
- Safe-area enforcement currently covers extractable SVG/PDF text only. Raster, vector
  decoration, and positioned QR/barcode geometry cannot yet be classified as critical content.

## Next operator steps

1. Add approved product specs and both passing/failing artwork fixtures for every SKU.
2. Add the licensed Callas adapter/profile when the printer supplies its preflight target.
3. Run the full verification commands recorded below for each release.

## Verification record

Verified on 2026-08-17 from commits `af7dae38db5f7fa8f1fbe4696181c44352e65bf3`
and `973430887cf710e5a517d5688f2e86a8d6da8dc3`:

```text
python3 -m pytest -q
python3 -m ruff check .                   # passed
python3 -m build                          # sdist and wheel created in dist/
python3 -m labelos.cli validate examples/label.json --json
python3 -m labelos.cli package examples/label.json /tmp/labelos-e2e --json
python3 -m labelos.cli verify-package /tmp/labelos-e2e --json
python3 -m labelos.cli doctor --json
```

Results: 12 tests passed; Ruff, bytecode compilation, and dependency checks passed; the sdist
and wheel were generated in `dist/`; and the end-to-end package was created and checksum-verified
at `/tmp/labelos-final-e2e`.
`doctor` confirmed PyMuPDF and ZXing-C++ are available; Callas pdfToolbox remains unavailable.
QR and Code 128 regression tests generate raster, SVG, and PDF fixtures and verify their
decoded expected values. GitHub Actions runs tests, lint, and builds on Python 3.10 and 3.12.
