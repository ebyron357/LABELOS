# Production readiness status

## Implemented

- JSON label specification validation with physical dimensions, bleed, safe-area constraints,
  minimum DPI, and required-copy fields.
- SVG, PNG, and PDF artwork validation through bundled PyMuPDF, including effective-DPI
  enforcement for every raster image embedded in a PDF.
- QR/barcode expected-value validation through bundled ZXing-C++; SVG and PDF artwork are
  rasterized at 300 DPI before decoding, and a decoder load failure is a validation error
  whenever code validation is requested.
- Safe-area enforcement for visible raster, SVG, and PDF content; validation fails closed when
  a uniform canvas background cannot be established.
- Operator CLI: validate, package, verify-package, and doctor.
- Schema-v2, immutable-style release directories containing copied artwork, a passing
  validation report, manifest, byte counts, and SHA-256 checksums. Verification rejects
  malformed manifests, symlinks, path traversal, report/spec inconsistencies, and untracked
  files.
- Passing and failing fixture coverage for code decoding, safe areas, package integrity, and
  PDF image resolution, plus CLI/package regression tests.

## Known external/human blockers

- **TOOL UNAVAILABLE/BLOCKED:** Callas pdfToolbox is not installed or configured. No Callas
  preflight/profile result is claimed.
- No approved production artwork, regulatory-copy source, printer ICC/color target, or
  prepress acceptance profile is in this repository. The software can validate supplied
  specifications, but cannot certify these absent requirements.

## Next operator steps

1. Add approved product specs and both passing/failing artwork fixtures for every SKU.
2. Add the licensed Callas adapter/profile when the printer supplies its preflight target.
3. Supply the printer ICC/color target and prepress acceptance profile before certifying a
   specific label for print.
4. Run the full verification commands recorded below for each release.

## Verification record

Verified on 2026-08-17 from commit `f03da71adf34522d674c57b3bebc2238f11f2850` plus the
PDF-resolution change in this working tree:

```text
python3 -m pytest -q                      # 18 passed
python3 -m ruff check .                   # passed
python3 -m compileall -q labelos tests    # passed
python3 -m pip check                      # passed
python3 -m build                          # sdist and wheel created in dist/
python3 -m labelos.cli validate examples/label.json --json
python3 -m labelos.cli package examples/label.json /tmp/labelos-e2e-c62b --json
python3 -m labelos.cli verify-package /tmp/labelos-e2e-c62b --json
python3 -m labelos.cli doctor --json
python3 -m pip install --no-deps --target /tmp/labelos-wheel-c62b \
  dist/labelos-0.1.0-py3-none-any.whl
PYTHONPATH=/tmp/labelos-wheel-c62b python3 -m labelos.cli validate \
  examples/label.json --json
PYTHONPATH=/tmp/labelos-wheel-c62b python3 -m labelos.cli package \
  examples/label.json /tmp/labelos-wheel-package-c62b --json
PYTHONPATH=/tmp/labelos-wheel-c62b python3 -m labelos.cli verify-package \
  /tmp/labelos-wheel-package-c62b --json
```

Results: 18 tests passed; Ruff, bytecode compilation, dependency consistency checks, source
CLI workflow, and isolated-wheel CLI workflow passed. The production package was created,
checksum-verified, deliberately tampered to prove rejection of an untracked file, restored, and
verified again. The sdist and wheel were generated in `dist/`.
`doctor` confirmed PyMuPDF and ZXing-C++ are available; Callas pdfToolbox remains unavailable.
QR and Code 128 regression tests generate raster, SVG, and PDF fixtures and verify their
decoded expected values. PDF raster-image DPI regression coverage includes both a rejected
72-DPI image and an accepted 600-DPI image. GitHub Actions runs tests, lint, and builds on
Python 3.10 and 3.12.
