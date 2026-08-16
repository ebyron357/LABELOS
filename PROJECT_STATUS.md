# Production readiness status

## Implemented

- JSON label specification validation with physical dimensions, bleed, safe-area sanity,
  minimum DPI, and required-copy fields.
- SVG, PNG, and PDF artwork validation through bundled PyMuPDF.
- Safe-area validation rasterizes SVG/PDF artwork at 300 DPI and rejects non-background
  artwork in the bleed plus configured protected margin. It fails closed if a raster has no
  visible content or an asset's outer corners do not establish a uniform bleed background.
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

Verified on 2026-08-16 from the safe-area validation change:

```text
python3 -m pytest -q --cache-clear        # 13 passed
python3 -m ruff check .                   # passed
python3 -m compileall -q labelos tests    # passed
python3 -m build                          # sdist and wheel created in dist/
python3 -m labelos.cli validate examples/label.json --json
python3 -m labelos.cli package examples/label.json /tmp/labelos-safe-area-e2e --json
python3 -m labelos.cli verify-package /tmp/labelos-safe-area-e2e --json
python3 -m labelos.cli doctor --json
python3 -m pip check
python3 -m pip install --no-deps --target /tmp/labelos-wheel-target dist/labelos-0.1.0-py3-none-any.whl
PYTHONPATH=/tmp/labelos-wheel-target python3 -m labelos.cli package examples/label.json /tmp/labelos-wheel-e2e --json
PYTHONPATH=/tmp/labelos-wheel-target python3 -m labelos.cli verify-package /tmp/labelos-wheel-e2e --json
```

Results: 13 tests passed, including passing SVG, failing PNG/PDF, and transparent-raster
safe-area cases; Ruff, bytecode compilation, and dependency checks passed; the sdist and
wheel were generated in `dist/`; and the end-to-end package was created and checksum-verified
at `/tmp/labelos-safe-area-e2e`. The built wheel was installed into
`/tmp/labelos-wheel-target` and its package/verification workflow passed at
`/tmp/labelos-wheel-e2e`. A virtualenv-based isolated-wheel test is blocked by this image's
missing `ensurepip`/`python3-venv`; this is an environment limitation, not treated as a
package pass. `doctor` confirmed PyMuPDF and ZXing-C++ are available; Callas pdfToolbox remains
TOOL UNAVAILABLE/BLOCKED. QR and Code 128 regression tests generate raster, SVG, and PDF
fixtures and verify their decoded expected values. GitHub Actions runs tests, lint, and builds
on Python 3.10 and 3.12.
