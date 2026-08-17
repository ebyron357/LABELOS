# Production readiness status

## Implemented

- JSON label specification validation with physical dimensions, bleed, safe-area sanity,
  minimum DPI, and required-copy fields.
- SVG, PNG, and PDF artwork validation through bundled PyMuPDF, including effective-DPI
  enforcement for every raster image embedded in a PDF.
- Fail-closed safe-area validation for extractable SVG/PDF text: reports the trim-safe bounds
  and rejects text that crosses them. Raster artwork and vector artwork without extractable text
  are reported as `SAFE_AREA_UNVERIFIABLE` rather than assumed safe.
- QR/barcode expected-value validation through bundled ZXing-C++; SVG and PDF artwork are
  rasterized at 300 DPI before decoding, and a decoder load failure is a validation error
  whenever code validation is requested.
- Operator CLI: validate, package, verify-package, and doctor.
- Immutable-style release directories containing copied artwork, validation report, manifest,
  and SHA-256 checksums, with fail-closed inventory, schema, byte-count, checksum,
  report-binding, and symbolic-link verification.
- Passing and failing fixture coverage plus CLI/package regression tests.

## Known external/human blockers

- **TOOL UNAVAILABLE/BLOCKED:** Callas pdfToolbox is not installed or configured. No Callas
  preflight/profile result is claimed.
- No approved production artwork, regulatory-copy source, printer ICC/color target, or
  prepress acceptance profile is in this repository. The software can validate supplied
  specifications, but cannot certify these absent requirements.

## Next engineering priority

1. Add reliable geometry validation for non-text vector artwork and positioned QR/barcodes; the
   current safe-area check deliberately does not treat those assets as verified.
2. Enforce effective DPI for raster images embedded in SVG artwork.

## Next operator steps

1. Add approved product specs and both passing/failing artwork fixtures for every SKU.
2. Add the licensed Callas adapter/profile when the printer supplies its preflight target.
3. Run the full verification commands recorded below for each release.

## Verification record

Verified on 2026-08-17 from commits `6d8405b` (PDF effective-DPI enforcement), `02aa587`
(extractable-text safe areas), and `0cedd6f` (package-integrity verification):

```text
python3 -m pytest -q                      # 17 passed
python3 -m ruff check .                   # passed
python3 -m compileall -q labelos tests    # passed
python3 -m pip check                      # passed
python3 -m build --outdir /tmp/labelos-build-package-integrity-6qDCJb
                                         # sdist and wheel created
python3 -m labelos.cli validate examples/label.json --json
python3 -m labelos.cli package examples/label.json /tmp/labelos-e2e-safe-area-983i12/release --json
python3 -m labelos.cli verify-package /tmp/labelos-e2e-safe-area-983i12/release --json
python3 -m labelos.cli doctor --json
python3 -m pip install --no-deps --target /tmp/labelos-wheel-safe-area-IugGQF \
  /tmp/labelos-build-safe-area-gTux8a/labelos-0.1.0-py3-none-any.whl
PYTHONPATH=/tmp/labelos-wheel-safe-area-IugGQF python3 -m labelos.cli validate \
  examples/label.json --json
```

Results: 17 tests passed; Ruff, bytecode compilation, and dependency consistency checks
passed; the sdist and wheel were created in `/tmp/labelos-build-package-integrity-6qDCJb`;
source CLI packaging was created and checksum-verified in
`/tmp/labelos-package-final-e2e-Qa74WA/release`; the isolated wheel validated the example
configuration.
`doctor` confirmed PyMuPDF and ZXing-C++ are available; Callas pdfToolbox remains unavailable.
QR and Code 128 regression tests generate raster, SVG, and PDF fixtures and verify their
decoded expected values. PDF raster-image DPI regression coverage includes both a rejected
72-DPI image and an accepted 600-DPI image; safe-area coverage includes accepted SVG text plus
rejected SVG and PDF text. Package-verification regressions reject extra files, package and
artifact symlinks, incorrect byte counts, checksum mismatches, and a validation-report/manifest
mismatch. GitHub Actions runs tests, lint, and builds on Python 3.10 and 3.12.
