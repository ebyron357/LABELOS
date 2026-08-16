# Production readiness status

## Implemented

- JSON label specification validation with physical dimensions, bleed, safe-area requirements,
  minimum DPI, and required-copy fields.
- SVG, PNG, and PDF artwork validation through bundled PyMuPDF.
- QR/barcode expected-value validation through bundled ZXing-C++; SVG and PDF artwork are
  rasterized at 300 DPI before decoding, and a decoder load failure is a validation error
  whenever code validation is requested.
- Fail-closed safe-area validation when `safe_area_mm` is configured: raster PNGs are inspected
  directly and SVG/PDF artwork is rendered at 300 DPI. Transparent PNGs and non-uniform opaque
  bleed edges are reported as `SAFE_AREA_UNCHECKABLE`; content in the protected frame is
  reported as `SAFE_AREA_VIOLATION`.
- Operator CLI: validate, package, verify-package, and doctor.
- Immutable-style release directories containing copied artwork, validation report, and schema
  v2 SHA-256/byte-size manifests. Verification rejects malformed or old manifests, unsafe file
  names, symlinks, failing reports, checksum or byte-size mismatches, and unexpected files.
- Passing and failing fixture coverage plus safe-area, code-decode, CLI, and package regression
  tests.

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

Verified on 2026-08-16 from the working branch before its next commit:

```text
python3 -m pytest -q --cache-clear        # 14 passed
python3 -m ruff check .                   # passed
python3 -m compileall -q labelos tests    # passed
python3 -m pip check                      # passed
python3 -m build --outdir /tmp/labelos-build-20260816-0909b
python3 -m labelos.cli validate examples/label.json --json
python3 -m labelos.cli package examples/label.json /tmp/labelos-e2e-20260816-0909b --json
python3 -m labelos.cli verify-package /tmp/labelos-e2e-20260816-0909b --json
python3 -m labelos.cli doctor --json
```

Results: 14 tests passed; Ruff, bytecode compilation, and dependency verification passed; the
sdist and wheel were generated in `/tmp/labelos-build-20260816-0909b`; and the end-to-end package
was created and integrity-verified at `/tmp/labelos-e2e-20260816-0909b`.
`doctor` confirmed PyMuPDF and ZXing-C++ are available; Callas pdfToolbox remains unavailable.
QR and Code 128 regression tests generate raster, SVG, and PDF fixtures and verify their decoded
expected values. Safe-area regression tests cover passing PNG/SVG/PDF artwork plus protected-edge
and transparent-PNG failures. GitHub Actions runs tests, lint, and builds on Python 3.10 and 3.12.
