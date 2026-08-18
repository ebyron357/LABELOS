# Production readiness status

## Implemented

- JSON label specification validation with physical dimensions, bleed, safe-area sanity,
  minimum DPI, and required-copy fields.
- SVG, PNG, and PDF artwork validation through bundled PyMuPDF, including effective-DPI
  enforcement for every raster image embedded in a PDF.
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

Verified on 2026-08-18 at commit `3b50df179f39f021388adfae883c8beda90659b6`:

```text
python3 -m pytest -q                      # 11 passed
python3 -m ruff check .                   # passed
python3 -m compileall -q labelos tests    # passed
python3 -m pip check                      # passed
python3 -m build --outdir /tmp/labelos-build-3b50df1
                                         # sdist and wheel created
python3 -m labelos.cli validate examples/label.json --json
python3 -m labelos.cli package examples/label.json /tmp/labelos-package-3b50df1 --json
python3 -m labelos.cli verify-package /tmp/labelos-package-3b50df1 --json
python3 -m labelos.cli doctor --json
python3 -m pip install --no-deps --target /tmp/labelos-wheel-3b50df1 \
  /tmp/labelos-build-3b50df1/labelos-0.1.0-py3-none-any.whl
PYTHONPATH=/tmp/labelos-wheel-3b50df1 python3 -m labelos.cli validate \
  examples/label.json --json
PYTHONPATH=/tmp/labelos-wheel-3b50df1 python3 -m labelos.cli package \
  examples/label.json /tmp/labelos-wheel-package-3b50df1 --json
PYTHONPATH=/tmp/labelos-wheel-3b50df1 python3 -m labelos.cli verify-package \
  /tmp/labelos-wheel-package-3b50df1 --json
```

Results: 11 tests passed; Ruff, bytecode compilation, and dependency consistency checks
passed; the sdist and wheel were created in `/tmp/labelos-build-3b50df1`; and
source and isolated-wheel CLI packages were created and checksum-verified.
`doctor` confirmed PyMuPDF and ZXing-C++ are available; Callas pdfToolbox remains unavailable.
QR and Code 128 regression tests generate raster, SVG, and PDF fixtures and verify their
decoded expected values. PDF raster-image DPI regression coverage includes both a rejected
72-DPI image and an accepted 600-DPI image. GitHub Actions runs tests, lint, and builds on
Python 3.10 and 3.12.
