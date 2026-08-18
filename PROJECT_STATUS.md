# Production readiness status

## Implemented

- JSON label specification validation with physical dimensions, bleed, safe-area bounds,
  minimum DPI, and required-copy fields.
- SVG, PNG, and PDF artwork validation through bundled PyMuPDF.
- QR/barcode expected-value validation through bundled ZXing-C++; SVG and PDF artwork are
  rasterized at 300 DPI before decoding, and a decoder load failure is a validation error
  whenever code validation is requested.
- Safe-area validation for PNG, SVG, and PDF artwork. It rasterizes vector artwork at 300 DPI,
  checks visible-content bounds against the bleed plus safe-area inset, and fails closed if a
  uniform canvas background cannot be established.
- Malformed PDFs yield a structured `PDF_INVALID` report instead of an operator-facing traceback.
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

Verified on 2026-08-18 from code commit `59dae38679d01902482d8a583feca3594795ee16`:

```text
python3 -m pytest -q                      # 12 passed
python3 -m ruff check .                   # passed
python3 -m compileall -q labelos tests    # passed
python3 -m pip check                      # passed
python3 -m build                          # sdist and wheel created in dist/
$HOME/.local/bin/labelos validate examples/label.json --json
$HOME/.local/bin/labelos package examples/label.json /tmp/tmp.4AfQTKtkBb/release --json
$HOME/.local/bin/labelos verify-package /tmp/tmp.4AfQTKtkBb/release --json
$HOME/.local/bin/labelos doctor --json
```

Results: 12 tests passed; Ruff, bytecode compilation, and dependency consistency checks passed;
the sdist and wheel were generated in `dist/`; and the end-to-end package was created and
checksum-verified at `/tmp/tmp.4AfQTKtkBb/release`. Regression coverage verifies both a safe
PNG and unsafe PNG/SVG/PDF artwork, as well as malformed-PDF JSON output without a traceback.
`doctor` confirmed PyMuPDF and ZXing-C++ are available; Callas pdfToolbox remains unavailable.
QR and Code 128 regression tests generate raster, SVG, and PDF fixtures and verify their
decoded expected values. GitHub Actions runs tests, lint, and builds on Python 3.10 and 3.12.
