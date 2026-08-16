# Production readiness status

## Implemented

- JSON label specification validation with physical dimensions, bleed, safe-area sanity,
  minimum DPI, and required-copy fields.
- SVG, PNG, and PDF artwork validation through bundled PyMuPDF.
- Fail-closed safe-area validation for SVG, PNG, and PDF artwork. Uniform full-bleed
  backgrounds are allowed; non-background content in `bleed_mm + safe_area_mm` fails with
  `SAFE_AREA_VIOLATION`, and an uninspectable edge fails with `SAFE_AREA_UNCHECKABLE`.
- QR/barcode expected-value validation through bundled ZXing-C++; SVG and PDF artwork are
  rasterized at 300 DPI before decoding, and a decoder load failure is a validation error
  whenever code validation is requested.
- Operator CLI: validate, package, verify-package, and doctor.
- Immutable-style release directories containing copied artwork, validation report, manifest,
  SHA-256 checksums, byte counts, specification/report consistency checks, and safe
  regular-file paths. Verification rejects malformed manifests and unexpected package files.
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

Verified on 2026-08-16 from implementation commit `46f01f0`:

```text
python3 -m pytest -q                      # 14 passed
python3 -m ruff check .                   # passed
python3 -m compileall -q labelos tests    # passed
python3 -m pip check                      # passed
python3 -m build --outdir /tmp/labelos-production-build-current
python3 -m labelos.cli validate examples/label.json --json
python3 -m labelos.cli package examples/label.json /tmp/labelos-production-e2e-current --json
python3 -m labelos.cli verify-package /tmp/labelos-production-e2e-current --json
python3 -m labelos.cli doctor --json
python3 -m pip install --target /tmp/labelos-wheel-target-current \
  /tmp/labelos-production-build-current/labelos-0.1.0-py3-none-any.whl
PYTHONPATH=/tmp/labelos-wheel-target-current python3 -m labelos.cli validate examples/label.json --json
PYTHONPATH=/tmp/labelos-wheel-target-current python3 -m labelos.cli package \
  examples/label.json /tmp/labelos-wheel-e2e-current --json
PYTHONPATH=/tmp/labelos-wheel-target-current python3 -m labelos.cli verify-package \
  /tmp/labelos-wheel-e2e-current --json
PYTHONPATH=/tmp/labelos-wheel-target-current python3 -m labelos.cli doctor --json
```

Results: 14 tests passed; Ruff, compilation, and dependency checks passed; the sdist and wheel
were generated in `/tmp/labelos-production-build-current`. The source checkout and the built
wheel both created and checksum/schema/byte-count verified release packages in
`/tmp/labelos-production-e2e-current` and `/tmp/labelos-wheel-e2e-current`, respectively.
`doctor` confirmed PyMuPDF and ZXing-C++ are available; Callas pdfToolbox remains unavailable.
QR and Code 128 regression tests generate raster, SVG, and PDF fixtures and verify their
decoded expected values. Safe-area tests cover passing SVG artwork and failing PNG/PDF artwork;
manifest tests cover checksum, byte-count, path-traversal, and unexpected-file rejection.
GitHub Actions runs tests, lint, and builds on Python 3.10 and 3.12.
