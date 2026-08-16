# Production readiness status

## Implemented

- JSON label specification validation with physical dimensions, bleed, safe-area sanity,
  minimum DPI, and required-copy fields.
- SVG, PNG, and PDF artwork validation through bundled PyMuPDF.
- Rasterized safe-area enforcement for PNG, SVG, and PDF artwork. Visible content must remain
  inside the configured trim-safe boundary; transparent or ambiguous canvases fail closed.
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

Verified on 2026-08-16 from implementation commit `9fcf4ee`:

```text
python3 -m pytest -q --cache-clear        # 12 passed
python3 -m ruff check .                   # passed
python3 -m compileall -q labelos tests    # passed
python3 -m pip check                      # passed
python3 -m build                          # sdist and wheel created in dist/
python3 -m labelos.cli validate examples/label.json --json
python3 -m labelos.cli package examples/label.json /tmp/labelos-e2e-*/release --json
python3 -m labelos.cli verify-package /tmp/labelos-e2e-*/release --json
python3 -m labelos.cli doctor --json
PYTHONPATH=/tmp/labelos-wheel-* python3 -m labelos.cli validate /workspace/examples/label.json --json
PYTHONPATH=/tmp/labelos-wheel-* python3 -m labelos.cli package /workspace/examples/label.json \
  /tmp/labelos-wheel-e2e-*/release --json
PYTHONPATH=/tmp/labelos-wheel-* python3 -m labelos.cli verify-package \
  /tmp/labelos-wheel-e2e-*/release --json
```

Results: 12 tests passed; Ruff, bytecode compilation, and dependency integrity checks passed;
the sdist and wheel were generated in `dist/`; and source and installed-wheel end-to-end
packages were created and checksum-verified at `/tmp/labelos-e2e-aerzxz/release` and
`/tmp/labelos-wheel-e2e-F5EjvG/release`. Safe-area fixtures cover valid content placement,
trim-safe violations, and transparent/ambiguous canvases.
`doctor` confirmed PyMuPDF and ZXing-C++ are available; Callas pdfToolbox remains unavailable.
QR and Code 128 regression tests generate raster, SVG, and PDF fixtures and verify their
decoded expected values. GitHub Actions runs tests, lint, and builds on Python 3.10 and 3.12.
