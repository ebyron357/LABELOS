# Production readiness status

## Implemented

- JSON label specification validation with physical dimensions, bleed, rendered safe-area
  enforcement, minimum DPI, and required-copy fields.
- SVG, PNG, and PDF artwork validation through bundled PyMuPDF, including effective-DPI
  enforcement for every raster image embedded in a PDF.
- QR/barcode expected-value validation through bundled ZXing-C++; SVG and PDF artwork are
  rasterized at 300 DPI before decoding, and a decoder load failure is a validation error
  whenever code validation is requested.
- Operator CLI: validate, package, verify-package, and doctor.
- Immutable-style release directories containing copied artwork, validation report, normalized
  label spec, manifest, and SHA-256 checksums. Verification rejects path traversal, symlinks,
  size/checksum mismatches, and non-passing or inconsistent package metadata.
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

Verified on 2026-08-18 from code commit `bac1f84`:

```text
python3 -m pytest -q                      # 24 passed
python3 -m ruff check .                   # passed
python3 -m compileall -q labelos tests    # passed
python3 -m pip check                      # passed
python3 -m build --outdir /tmp/labelos-production-build-d194
                                         # sdist and wheel created
python3 -m labelos.cli validate examples/label.json --json
python3 -m labelos.cli package examples/label.json /tmp/labelos-source-package-d194 --json
python3 -m labelos.cli verify-package /tmp/labelos-source-package-d194 --json
python3 -m labelos.cli doctor --json
python3 -m pip install --no-deps --target /tmp/labelos-wheel-target-d194 \
  /tmp/labelos-production-build-d194/labelos-0.1.0-py3-none-any.whl
PYTHONPATH=/tmp/labelos-wheel-target-d194 python3 -m labelos.cli validate \
  examples/label.json --json
PYTHONPATH=/tmp/labelos-wheel-target-d194 python3 -m labelos.cli package \
  examples/label.json /tmp/labelos-wheel-package-d194 --json
PYTHONPATH=/tmp/labelos-wheel-target-d194 python3 -m labelos.cli verify-package \
  /tmp/labelos-wheel-package-d194 --json
```

Results: 24 tests passed; Ruff, bytecode compilation, and dependency consistency checks
passed; the sdist and wheel were created in `/tmp/labelos-production-build-d194`; and source
and isolated-wheel CLI packages were created and checksum-verified.
`doctor` confirmed PyMuPDF and ZXing-C++ are available; Callas pdfToolbox remains unavailable.
QR and Code 128 regression tests generate raster, SVG, and PDF fixtures and verify their
decoded expected values. Regression coverage includes safe-area boundaries, malformed artwork,
release package tampering, PDF raster-image DPI (rejected 72-DPI and accepted 600-DPI images),
and source/wheel CLI packaging. GitHub Actions runs tests, lint, and builds on Python 3.10 and
3.12.
