# Production readiness status

## Implemented

- JSON label specification validation with physical dimensions, bleed, safe-area sanity,
  minimum DPI, and required-copy fields.
- Fail-closed safe-area validation when `safe_area_mm` is configured. PNG artwork must have
  an opaque, uniform edge background; SVG and PDF artwork are rasterized at 300 DPI and checked
  for non-background content inside the combined bleed-plus-safe-area boundary.
- SVG, PNG, and PDF artwork validation through bundled PyMuPDF.
- QR/barcode expected-value validation through bundled ZXing-C++; SVG and PDF artwork are
  rasterized at 300 DPI before decoding, and a decoder load failure is a validation error
  whenever code validation is requested.
- Operator CLI: validate, package, verify-package, and doctor.
- Immutable-style release directories containing copied artwork, validation report, manifest,
  SHA-256 checksums, byte sizes, and strict unexpected-file/path verification.
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

Verified on 2026-08-16 from the working tree based on commit
`1e86abd` (the resulting commit is recorded in this run's delivery):

```text
python3 -m pytest -q --cache-clear        # 13 passed
python3 -m ruff check .                   # passed
python3 -m compileall -q labelos tests    # passed
python3 -m build --outdir /tmp/labelos-build-20260816-1009-final
python3 -m labelos.cli validate examples/label.json --json
python3 -m labelos.cli package examples/label.json /tmp/labelos-e2e-20260816-1009-final --json
python3 -m labelos.cli verify-package /tmp/labelos-e2e-20260816-1009-final --json
python3 -m labelos.cli doctor --json
python3 -m pip check                       # passed
```

Results: 14 tests passed, including passing, protected-boundary failure, transparent-artwork
failure, malformed-PDF, and package-path/unexpected-file regressions. Ruff, compilation, package
build, and dependency checks passed. The sdist and wheel were generated in
`/tmp/labelos-build-20260816-1009-final`; the end-to-end package was created and
checksum-verified at `/tmp/labelos-e2e-20260816-1009-final`.
`doctor` confirmed PyMuPDF and ZXing-C++ are available; Callas pdfToolbox remains unavailable.
QR and Code 128 regression tests generate raster, SVG, and PDF fixtures and verify their
decoded expected values. GitHub Actions runs tests, lint, and builds on Python 3.10 and 3.12.
