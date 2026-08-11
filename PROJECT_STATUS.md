# Production readiness status

## Implemented

- JSON label specification validation with physical dimensions, bleed, safe-area sanity,
  minimum DPI, and required-copy fields.
- SVG, PNG, and PDF artwork validation through bundled PyMuPDF.
- QR/barcode expected-value validation through bundled ZXing-C++; SVG and PDF artwork are
  rasterized at 300 DPI before decoding, and a decoder load failure is a validation error
  whenever code validation is requested.
- Safe-area validation for PNG, SVG, and PDF artwork. LABELOS renders vector files at 300 DPI,
  detects non-background content against a corner-sampled canvas background, and rejects content
  outside the configured bleed-plus-safe-area boundary. Unrenderable artwork fails closed.
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

Verified on 2026-08-11 from the current change set:

```text
python3 -m pytest -q                      # 12 passed
python3 -m ruff check .                   # passed
python3 -m compileall -q labelos          # passed
python3 -m build --outdir /tmp/labelos-build  # sdist and wheel created
python3 -m pip check                      # passed
python3 -m labelos.cli validate examples/label.json --json
python3 -m labelos.cli package examples/label.json /tmp/labelos-safe-area-e2e --json
python3 -m labelos.cli verify-package /tmp/labelos-safe-area-e2e --json
python3 -m labelos.cli doctor --json
```

Results: 12 tests passed; Ruff, bytecode compilation, package build, and dependency validation
passed; the sdist and wheel were generated in `/tmp/labelos-build`; and the end-to-end package
was created and checksum-verified at `/tmp/labelos-safe-area-e2e`.
`doctor` confirmed PyMuPDF and ZXing-C++ are available; Callas pdfToolbox remains unavailable.
QR and Code 128 regression tests generate raster, SVG, and PDF fixtures and verify their
decoded expected values. Safe-area regression tests cover passing full-bleed uniform PNG
backgrounds and failing PNG/SVG content outside the allowed bounds. GitHub Actions runs tests,
lint, and builds on Python 3.10 and 3.12.
