# Production readiness status

## Implemented

- JSON label specification validation with physical dimensions, bleed, safe-area sanity,
  minimum DPI, and required-copy fields.
- SVG, PNG, and PDF artwork validation through bundled PyMuPDF.
- QR/barcode expected-value validation through bundled ZXing-C++; SVG and PDF artwork are
  rasterized at 300 DPI before decoding, and a decoder load failure is a validation error
  whenever code validation is requested.
- Operator CLI: validate, package, verify-package, and doctor.
- Immutable-style release directories containing copied artwork, validation report, manifest,
  canonical package-local label spec, and SHA-256 checksums.
- Package verification rejects unsafe paths and symlinks; verifies regular files, byte counts,
  lowercase SHA-256 digests, a passing report, and report/spec/manifest agreement.
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

Verified on 2026-08-10 from code commit `b0a317d14f75796f458f813d6353d2bb3db6016b`:

```text
python3 -m pytest -q                      # 11 passed
python3 -m ruff check .                   # passed
python3 -m compileall -q labelos          # passed
python3 -m build --outdir /tmp/labelos-build
python3 -m labelos.cli validate examples/label.json --json
python3 -m labelos.cli package examples/label.json /tmp/labelos-e2e --json
python3 -m labelos.cli verify-package /tmp/labelos-e2e --json
python3 -m labelos.cli doctor --json
```

Results: 11 tests passed; Ruff and compile checks passed; the sdist and wheel were generated in
`/tmp/labelos-build`; and the end-to-end package was created and checksum-verified at
`/tmp/labelos-e2e`. Regression coverage includes malformed PDFs, release-report tampering, and
unsafe package paths, in addition to raster/vector QR and Code 128 decoding.
`doctor` confirmed PyMuPDF and ZXing-C++ are available; Callas pdfToolbox remains unavailable.
QR and Code 128 regression tests generate raster, SVG, and PDF fixtures and verify their
decoded expected values. GitHub Actions runs tests, lint, and builds on Python 3.10 and 3.12.
