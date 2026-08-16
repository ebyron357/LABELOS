# Production readiness status

## Implemented

- JSON label specification validation with physical dimensions, bleed, rendered safe-area
  bounds, minimum DPI, and required-copy fields.
- SVG, PNG, and PDF artwork validation through bundled PyMuPDF, including structured
  `PDF_INVALID` errors instead of CLI crashes for unreadable PDFs.
- QR/barcode expected-value validation through bundled ZXing-C++; SVG and PDF artwork are
  rasterized at 300 DPI before decoding, and a decoder load failure is a validation error
  whenever code validation is requested.
- Operator CLI: validate, package, verify-package, and doctor.
- Immutable-style release directories containing copied artwork, validation report, manifest,
  and SHA-256 checksums. Verification rejects malformed schema entries, unsafe paths,
  symlinks, byte-count mismatches, and untracked files.
- Passing and failing fixture coverage plus CLI/package, safe-area, and malformed-PDF
  regression tests.

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

Verified on 2026-08-16 from implementation commit `668be1a`:

```text
python3 -m pytest -q                      # 14 passed
python3 -m ruff check .                   # passed
python3 -m compileall -q labelos          # passed
python3 -m pip check                      # no broken requirements
python3 -m build                          # sdist and wheel created in dist/
python3 -m labelos.cli validate examples/label.json --json
python3 -m labelos.cli package examples/label.json /tmp/labelos-e2e-20260816 --json
python3 -m labelos.cli verify-package /tmp/labelos-e2e-20260816 --json
python3 -m labelos.cli doctor --json
```

Results: 14 tests passed; Ruff, compile, and dependency checks passed; the sdist and wheel
were generated in `dist/`; and the end-to-end package was created and checksum-verified at
`/tmp/labelos-e2e-20260816`. The wheel installed to `/tmp/labelos-wheel-20260816` also
validated, packaged, and verified the example successfully.
`doctor` confirmed PyMuPDF and ZXing-C++ are available; Callas pdfToolbox remains unavailable.
QR and Code 128 regression tests generate raster, SVG, and PDF fixtures and verify their
decoded expected values. GitHub Actions runs tests, lint, and builds on Python 3.10 and 3.12.
