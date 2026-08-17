# Production readiness status

## Implemented

- JSON label specification validation with physical dimensions, bleed, enforced safe-area,
  minimum DPI, and required-copy fields.
- SVG, PNG, and PDF artwork validation through bundled PyMuPDF.
- Fail-closed safe-area inspection: SVG/PDF artwork is rasterized at 300 DPI and PNG is
  inspected directly. Non-background content outside the trim-safe inset, ambiguous corner
  backgrounds, and transparent PNG artwork fail validation.
- QR/barcode expected-value validation through bundled ZXing-C++; SVG and PDF artwork are
  rasterized at 300 DPI before decoding, and a decoder load failure is a validation error
  whenever code validation is requested.
- Operator CLI: validate, package, verify-package, and doctor.
- Immutable-style release directories containing copied artwork, validation report, manifest,
  and SHA-256/byte-count integrity data. Verification rejects malformed schema, unsafe
  filenames, symlinks, unexpected files, checksum/byte-count changes, and report/spec
  inconsistencies.
- Passing and failing SVG/PNG safe-area coverage plus CLI/package regression tests.

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

Verified on 2026-08-17 from the current production-readiness change set:

```text
python3 -m pytest -q                      # 14 passed
python3 -m ruff check .                   # passed
python3 -m compileall -q labelos tests    # passed
python3 -m pip check                      # passed
python3 -m build --outdir /tmp/labelos-production-build-20260817
                                         # sdist and wheel created
python3 -m labelos.cli validate examples/label.json --json
python3 -m labelos.cli package examples/label.json /tmp/labelos-e2e-20260817 --json
python3 -m labelos.cli verify-package /tmp/labelos-e2e-20260817 --json
python3 -m labelos.cli doctor --json
python3 -m pip install --no-deps --target /tmp/labelos-wheel-target-20260817 \
  /tmp/labelos-production-build-20260817/labelos-0.1.0-py3-none-any.whl
PYTHONPATH=/tmp/labelos-wheel-target-20260817 python3 -m labelos.cli validate \
  examples/label.json --json
PYTHONPATH=/tmp/labelos-wheel-target-20260817 python3 -m labelos.cli package \
  examples/label.json /tmp/labelos-wheel-package-20260817 --json
PYTHONPATH=/tmp/labelos-wheel-target-20260817 python3 -m labelos.cli verify-package \
  /tmp/labelos-wheel-package-20260817 --json
```

Results: 14 tests passed; Ruff, bytecode compilation, and dependency consistency checks
passed; the sdist and wheel were generated in `/tmp/labelos-production-build-20260817`; and
the end-to-end package was created and integrity-verified at `/tmp/labelos-e2e-20260817`.
`doctor` confirmed PyMuPDF and ZXing-C++ are available; Callas pdfToolbox remains unavailable.
The built wheel was installed into an isolated target directory and validated through the same
CLI workflow. QR and Code 128 regression tests generate raster, SVG, and PDF fixtures and
verify their decoded expected values. GitHub Actions runs tests, lint, and builds on Python
3.10 and 3.12.
