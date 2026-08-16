# Production readiness status

## Implemented

- JSON label specification validation with physical dimensions, bleed, safe-area settings,
  minimum DPI, and required-copy fields.
- SVG, PNG, and PDF artwork validation through bundled PyMuPDF.
- Safe-area artwork enforcement for SVG, PNG, and PDF. It permits uniform full-bleed
  backgrounds, rejects non-background content in the bleed-plus-safe margin, and fails closed
  when an edge background cannot be reliably checked.
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

Verified on 2026-08-16 for implementation commit `3af6425`:

```text
python3 -m pytest -q --cache-clear        # 13 passed
python3 -m ruff check .                   # passed
python3 -m build                          # sdist and wheel created in dist/
python3 -m compileall -q labelos          # passed
python3 -m pip check                      # no broken requirements
python3 -m labelos.cli validate examples/label.json --json
python3 -m labelos.cli package examples/label.json /tmp/labelos-safe-area-e2e --json
python3 -m labelos.cli verify-package /tmp/labelos-safe-area-e2e --json
python3 -m labelos.cli doctor --json
PYTHONPATH=/tmp/labelos-wheel-e2e python3 -m labelos.cli validate /workspace/examples/label.json --json
PYTHONPATH=/tmp/labelos-wheel-e2e python3 -m labelos.cli package /workspace/examples/label.json /tmp/labelos-wheel-release --json
PYTHONPATH=/tmp/labelos-wheel-e2e python3 -m labelos.cli verify-package /tmp/labelos-wheel-release --json
```

Results: 13 tests passed; Ruff, compile, dependency, and build checks passed. The source
end-to-end package was created and checksum-verified at `/tmp/labelos-safe-area-e2e`; the built
wheel was installed into `/tmp/labelos-wheel-e2e` and independently validated and
checksum-verified at `/tmp/labelos-wheel-release`.
`doctor` confirmed PyMuPDF and ZXing-C++ are available; Callas pdfToolbox remains unavailable.
QR and Code 128 regression tests generate raster, SVG, and PDF fixtures and verify their
decoded expected values. Safe-area regressions cover a passing full-bleed SVG, failing PNG/PDF
margin content, and transparent PNG artwork. GitHub Actions runs tests, lint, and builds on
Python 3.10 and 3.12.
