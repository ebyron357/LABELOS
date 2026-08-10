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
  package-local label specification, and SHA-256 checksums.
- Package verification rejects missing or symlinked files, traversal filenames, malformed
  digests, byte-count mismatches, non-passing reports, and inconsistent package metadata.
- Invalid PDF input is returned as a `PDF_INVALID` validation result instead of a traceback.
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

Verified on 2026-08-10 from commit `20a4c08d0eae993081df7ad811401bea05751af4`:

```text
python3 -m pytest -q                      # 16 passed
python3 -m ruff check .                   # passed
python3 -m compileall -q labelos          # passed
python3 -m build --outdir /tmp/labelos-build-safe-area # sdist and wheel created
python3 -m labelos.cli validate examples/label.json --json
python3 -m labelos.cli package examples/label.json /tmp/labelos-safe-area-e2e --json
python3 -m labelos.cli verify-package /tmp/labelos-safe-area-e2e --json
python3 -m labelos.cli doctor --json
```

Results: 16 tests passed; Ruff and bytecode compilation passed; the sdist and wheel were
generated in `/tmp/labelos-build-safe-area`; and the end-to-end package was created and
checksum-verified at `/tmp/labelos-safe-area-e2e`.
`doctor` confirmed PyMuPDF and ZXing-C++ are available; Callas pdfToolbox remains unavailable.
QR and Code 128 regression tests generate raster, SVG, and PDF fixtures and verify their
decoded expected values. GitHub Actions runs tests, lint, and builds on Python 3.10 and 3.12.
