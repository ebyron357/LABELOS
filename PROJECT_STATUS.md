# Production readiness status

## Implemented

- JSON label specification validation with physical dimensions, bleed, safe-area sanity,
  minimum DPI, and required-copy fields.
- SVG, PNG, and PDF artwork validation through bundled PyMuPDF.
- Effective DPI enforcement for every displayed embedded raster image in PDF artwork, with
  per-image pixel dimensions, placed size, and calculated resolution in JSON reports.
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

## Next software priority

- Add effective-DPI validation for raster images embedded in SVG artwork. SVGs can reference
  low-resolution bitmap assets, but that inspection is not implemented yet. Keep PDF embedded
  raster enforcement covered by its passing and failing regression fixtures.

## Verification record

Verified on 2026-08-09 from commit `0fbe2c760154c772e2eb424971b882ce52919874`:

```text
python3 -m pytest                         # 9 passed
python3 -m ruff check .                   # passed
python3 -m build                          # sdist and wheel created in dist/
python3 -m labelos.cli validate examples/label.json --json
python3 -m labelos.cli package examples/label.json /tmp/labelos-e2e --json
python3 -m labelos.cli verify-package /tmp/labelos-e2e --json
python3 -m labelos.cli doctor --json
```

Results: 9 tests passed; Ruff passed; the sdist and wheel were generated in `dist/`; and the
end-to-end package was created and checksum-verified at `/tmp/labelos-e2e`.
`doctor` confirmed PyMuPDF and ZXing-C++ are available; Callas pdfToolbox remains unavailable.
QR and Code 128 regression tests generate raster, SVG, and PDF fixtures and verify their
decoded expected values. GitHub Actions runs tests, lint, and builds on Python 3.10 and 3.12.

Verified on 2026-08-17 (pre-commit):

```text
python3 -m pytest -q                      # 11 passed
python3 -m ruff check .                   # passed
python3 -m compileall -q labelos tests    # passed
python3 -m build --outdir /tmp/labelos-final-build
python3 -m labelos.cli validate examples/label.json --json
python3 -m labelos.cli package examples/label.json /tmp/labelos-final-e2e --json
python3 -m labelos.cli verify-package /tmp/labelos-final-e2e --json
python3 -m labelos.cli doctor --json
git diff --check                          # passed
```

This verification includes regression fixtures for a 304.8 DPI embedded PDF raster that passes
and a 72 DPI embedded PDF raster that fails with `PDF_IMAGE_DPI_TOO_LOW`. The build produced
`labelos-0.1.0.tar.gz` and `labelos-0.1.0-py3-none-any.whl` in
`/tmp/labelos-final-build`; the CLI package at `/tmp/labelos-final-e2e` passed checksum
verification. PyMuPDF and ZXing-C++ were available; Callas pdfToolbox remained
**TOOL UNAVAILABLE/BLOCKED**.
