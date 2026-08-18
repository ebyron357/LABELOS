# Production readiness status

## Implemented

- JSON label specification validation with physical dimensions, bleed, safe-area sanity,
  minimum DPI, and required-copy fields.
- SVG, PNG, and PDF artwork validation through bundled PyMuPDF.
- Effective-DPI checks for every raster image embedded in a PDF, with invalid PDFs failing
  closed instead of aborting the operator workflow.
- QR/barcode expected-value validation through bundled ZXing-C++; SVG and PDF artwork are
  rasterized at 300 DPI before decoding, and a decoder load failure is a validation error
  whenever code validation is requested.
- Operator CLI: validate, package, verify-package, and doctor.
- Immutable-style release directories containing copied artwork, validation report, manifest,
  and SHA-256 checksums; package verification rejects unsupported schemas, malformed entries,
  symlinks, and manifest path traversal.
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

## Remaining engineering priority

- The current `safe_area_mm` setting rejects impossible specifications but does not yet inspect
  all SVG/PDF object geometry against the safe-area boundary. This remains the next actionable
  software task; color-profile and printer-specific preflight checks remain dependent on the
  external acceptance profile.

## Verification record

Verified on 2026-08-18 from commits `be83572afa7f44454853148898530a348862c36e` and
`184815f5841015d8716e9d181bd7f86ff19e8ac4`:

```text
python3 -m pytest -q                      # 13 passed
python3 -m ruff check .                   # passed
python3 -m compileall -q labelos tests    # passed
python3 -m pip check                      # passed
python3 -m build                          # sdist and wheel created in dist/
python3 -m labelos.cli package examples/label.json /tmp/labelos-package-verification --json
python3 -m labelos.cli verify-package /tmp/labelos-package-verification --json
python3 -m labelos.cli doctor --json
```

Results: 13 tests passed; Ruff, compilation, and dependency checks passed; the sdist and wheel
were generated in `dist/`; and the end-to-end package was created and checksum-verified at
`/tmp/labelos-package-verification`.
`doctor` confirmed PyMuPDF and ZXing-C++ are available; Callas pdfToolbox remains unavailable.
QR and Code 128 regression tests generate raster, SVG, and PDF fixtures and verify their decoded
expected values. PDF regression tests cover low and high embedded-image DPI plus corrupt PDFs;
package tests cover manifest traversal rejection. GitHub Actions runs tests, lint, and builds on
Python 3.10 and 3.12.
