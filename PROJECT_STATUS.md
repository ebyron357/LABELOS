# Production readiness status

## Implemented

- JSON label specification validation with physical dimensions, bleed, trim-safe bounds,
  minimum DPI, and required-copy fields.
- SVG, PNG, and PDF artwork validation through bundled PyMuPDF, including rendered
  trim-safe-area checks and effective-DPI checks for placed PDF raster images.
- QR/barcode expected-value validation through bundled ZXing-C++; SVG and PDF artwork are
  rasterized at 300 DPI before decoding, and a decoder load failure is a validation error
  whenever code validation is requested.
- Operator CLI: validate, package, verify-package, and doctor.
- Immutable-style release directories containing copied artwork, resolved label specification,
  validation report, manifest, and SHA-256 checksums.
- Package verification rejects path traversal, malformed manifest entries, non-regular files,
  checksum/byte-count tampering, and inconsistent release metadata.
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

Verified on 2026-08-18 from code commits `f93823a` and
`d9d890aece63d53cf5ad952233461c8405d53ee9`:

```text
python3 -m pytest -q                      # 24 passed
python3 -m ruff check .                   # passed
python3 -m compileall -q labelos          # passed
python3 -m pip check                      # no broken requirements
python3 -m build --outdir /tmp/labelos-build  # sdist and wheel created
python3 -m labelos.cli validate examples/label.json --json
python3 -m labelos.cli package examples/label.json /tmp/labelos-e2e --json
python3 -m labelos.cli verify-package /tmp/labelos-e2e --json
python3 -m labelos.cli doctor --json
```

Results: 24 tests passed; Ruff, compilation, and dependency checks passed; the sdist and wheel
were generated in `/tmp/labelos-build`; and the end-to-end package was created and
checksum-verified at `/tmp/labelos-e2e`.
`doctor` confirmed PyMuPDF and ZXing-C++ are available; Callas pdfToolbox remains unavailable.
QR and Code 128 regression tests generate raster, SVG, and PDF fixtures and verify decoded
expected values. Safe-area, malformed-artwork, package-integrity, and PDF image-DPI regression
tests are included. GitHub Actions runs tests, lint, and builds on Python 3.10 and 3.12.
