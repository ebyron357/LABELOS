# Production readiness status

## Implemented

- JSON label specification validation with physical dimensions, bleed, safe-area sanity,
  minimum DPI, and required-copy fields.
- SVG, PNG, and PDF artwork validation through bundled PyMuPDF.
- QR/barcode expected-value validation through bundled ZXing-C++; SVG and PDF artwork are
  rasterized at 300 DPI before decoding, and a decoder load failure is a validation error
  whenever code validation is requested.
- Operator CLI: validate, package, verify-package, and doctor.
- Immutable-style release directories containing copied artwork, a canonical label specification,
  validation report, manifest, byte counts, and SHA-256 checksums.
- Release verification rejects malformed manifests, unsafe entry names and symlinks, checksum or
  byte-count mismatches, missing canonical specifications, and reports that do not document a
  passing validation result.
- Passing and failing fixture coverage plus CLI/package regression tests.
- Invalid PDF artwork yields a `PDF_INVALID` validation error instead of a traceback.

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

Verified on 2026-08-10 from commit `c528ab8`:

```text
python3 -m pytest -q                      # 14 passed
python3 -m ruff check .                   # passed
python3 -m compileall -q labelos          # passed
python3 -m build --outdir /tmp/labelos-build-hardened
                                           # sdist and wheel created
python3 -m labelos.cli validate examples/label.json --json
python3 -m labelos.cli package examples/label.json /tmp/labelos-e2e-hardened --json
python3 -m labelos.cli verify-package /tmp/labelos-e2e-hardened --json
python3 -m labelos.cli doctor --json
```

Results: 14 tests passed; Ruff and compilation passed; the sdist and wheel were generated in
`/tmp/labelos-build-hardened`; and the end-to-end package was created and fully
integrity-verified at `/tmp/labelos-e2e-hardened`.
`doctor` confirmed PyMuPDF and ZXing-C++ are available; Callas pdfToolbox remains unavailable.
QR and Code 128 regression tests generate raster, SVG, and PDF fixtures and verify their
decoded expected values. GitHub Actions runs tests, lint, and builds on Python 3.10 and 3.12.
