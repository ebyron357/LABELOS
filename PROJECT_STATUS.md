# Production readiness status

## Implemented

- JSON label specification validation with physical dimensions, bleed, safe-area sanity,
  minimum DPI, and required-copy fields.
- SVG, PNG, and PDF artwork validation through bundled PyMuPDF.
- QR/barcode expected-value validation through bundled ZXing-C++; SVG and PDF artwork are
  rasterized at 300 DPI before decoding, and a decoder load failure is a validation error
  whenever code validation is requested.
- Operator CLI: validate, package, verify-package, and doctor.
- Atomic release-package creation with a schema-v2 manifest containing tracked file names,
  byte counts, and SHA-256 checksums. Verification rejects malformed manifests, path traversal,
  checksum/byte-count mismatches, and untracked files.
- Effective-DPI validation for raster images embedded in PDFs.
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

Verified on 2026-08-17:

```text
python3 -m pytest -q                      # 12 passed
python3 -m ruff check .                   # passed
python3 -m compileall -q labelos tests    # passed
python3 -m pip check                      # passed
python3 -m build                          # sdist and wheel created in dist/
python3 -m labelos.cli validate examples/label.json --json
python3 -m labelos.cli package examples/label.json /tmp/labelos-e2e --json
python3 -m labelos.cli verify-package /tmp/labelos-e2e --json
python3 -m labelos.cli doctor --json
python3 -m pip install --no-deps --target /tmp/labelos-wheel dist/labelos-0.1.0-py3-none-any.whl
PYTHONPATH=/tmp/labelos-wheel python3 -m labelos.cli validate examples/label.json --json
```

Results: 12 tests passed; Ruff, bytecode compilation, and dependency checks passed; the sdist
and wheel were generated in `dist/`; and the end-to-end package was created and checksum-verified
at a temporary `/tmp/labelos-e2e.*` path. Adding an untracked file caused
`verify-package` to fail as designed. The built wheel was installed into an isolated target
directory and successfully ran `validate` and `doctor`. A fully isolated `venv` could not be
created because this base image lacks `ensurepip`; this does not affect the target-install test.
`doctor` confirmed PyMuPDF and ZXing-C++ are available; Callas pdfToolbox remains unavailable.
QR and Code 128 regression tests generate raster, SVG, and PDF fixtures and verify their
decoded expected values. GitHub Actions runs tests, lint, and builds on Python 3.10 and 3.12.
