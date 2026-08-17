# Production readiness status

## Implemented

- JSON label specification validation with physical dimensions, bleed, safe-area content
  enforcement, minimum DPI, and required-copy fields.
- SVG, PNG, and PDF artwork validation through bundled PyMuPDF.
- Safe-area enforcement rasterizes SVG/PDF artwork at 300 DPI and checks PNG pixels directly.
  It fails closed when non-background artwork enters the configured margin inside trim; the
  bleed is intentionally excluded.
- QR/barcode expected-value validation through bundled ZXing-C++; SVG and PDF artwork are
  rasterized at 300 DPI before decoding, and a decoder load failure is a validation error
  whenever code validation is requested.
- Operator CLI: validate, package, verify-package, and doctor.
- Immutable-style release directories containing copied artwork, validation report, manifest,
  byte sizes, and SHA-256 checksums. Schema v2 verification rejects unsafe paths, symlinks,
  unexpected files, checksum/byte changes, non-passing reports, and report/spec mismatches.
- Passing and failing SVG safe-area fixtures plus raster/PDF safe-area, code-decoding,
  CLI, and package-integrity regression tests.

## Known external/human blockers

- **TOOL UNAVAILABLE/BLOCKED:** Callas pdfToolbox is not installed or configured. No Callas
  preflight/profile result is claimed.
- No approved production artwork, regulatory-copy source, printer ICC/color target, or
  prepress acceptance profile is in this repository. The software can validate supplied
  specifications, but cannot certify these absent requirements.

## Next operator steps

1. Add approved product specs and artwork fixtures for every SKU.
2. Add the licensed Callas adapter/profile when the printer supplies its preflight target.
3. Supply printer ICC/color targets and the approved regulatory-copy source, then run the
   full verification commands below for each release.

## Verification record

Verified on 2026-08-17 from implementation commit
`60c9a33229c95daf601d54bcced1f77bf377ea4d`:

```text
python3 -m pytest -q                      # 14 passed
python3 -m ruff check .                   # passed
python3 -m compileall -q labelos tests    # passed
python3 -m build --outdir /tmp/labelos-final-build
python3 -m labelos.cli validate examples/label.json --json
python3 -m labelos.cli package examples/label.json /tmp/labelos-final-e2e --json
python3 -m labelos.cli verify-package /tmp/labelos-final-e2e --json
python3 -m labelos.cli doctor --json
```

Results: 14 tests passed; Ruff and compilation passed; sdist and wheel were generated in
`/tmp/labelos-final-build`; and the end-to-end package was created and checksum-verified at
`/tmp/labelos-final-e2e`. The passing fixture recorded zero safe-area content pixels; safe-area
failure fixtures for SVG, PNG, and PDF report `SAFE_AREA_CONTENT`. Package tests also reject
unexpected files, unsafe manifest paths, and altered/non-passing reports.
`doctor` confirmed PyMuPDF and ZXing-C++ are available; Callas pdfToolbox remains unavailable.
QR and Code 128 regression tests generate raster, SVG, and PDF fixtures and verify decoded
expected values. GitHub Actions runs tests, lint, and builds on Python 3.10 and 3.12.
