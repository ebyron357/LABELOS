# Production readiness status

## Implemented

- JSON label specification validation with physical dimensions, bleed, safe-area sanity,
  minimum DPI, and required-copy fields.
- SVG, PNG, and PDF artwork validation through bundled PyMuPDF.
- QR/barcode expected-value validation through bundled ZXing-C++; SVG and PDF artwork are
  rasterized at 300 DPI before decoding, and a decoder load failure is a validation error
  whenever code validation is requested.
- Safe-area enforcement for PNG pixels, SVG text/images/rects, and PDF text/images/vector
  drawings. Unsupported SVG visual primitives and transforms fail closed.
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

Verified on 2026-08-11 from code commit `40d3e7fb6029489acf1e1d924771f5e32bf5231a`:

```text
python3 -m pytest -q                      # 13 passed
python3 -m ruff check .                   # passed
python3 -m compileall -q labelos          # passed
python3 -m build --outdir /tmp/labelos-build-safe-area
                                          # sdist and wheel created
python3 -m labelos.cli validate examples/label.json --json
python3 -m labelos.cli package examples/label.json /tmp/labelos-safe-area-e2e --json
python3 -m labelos.cli verify-package /tmp/labelos-safe-area-e2e --json
python3 -m labelos.cli doctor --json
```

Results: all 13 tests passed; Ruff and compilation passed; the sdist and wheel were built in
`/tmp/labelos-build-safe-area`; and the end-to-end package was created and checksum-verified at
`/tmp/labelos-safe-area-e2e`. The successful CLI report includes the `safe-area` check; the
new regression coverage verifies passing PNG and failing SVG/PDF artwork, plus fail-closed
handling of unsupported SVG paths. `doctor` confirmed PyMuPDF and ZXing-C++ are available;
Callas pdfToolbox remains unavailable. QR and Code 128 regression tests generate raster, SVG,
and PDF fixtures and verify their decoded expected values. GitHub Actions runs tests, lint, and
builds on Python 3.10 and 3.12.

## Next software priority

Convert malformed PDF reader errors into structured `PDF_INVALID` reports so CLI operators do
not receive a traceback for corrupt artwork. Then harden release-package verification with a
canonical spec, byte counts, report-pass checks, and traversal/symlink rejection.
