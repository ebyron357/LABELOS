# Production readiness status

## Implemented

- JSON label specification validation with physical dimensions, bleed, safe-area sanity,
  minimum DPI, and required-copy fields. Extractable SVG/PDF text must remain within the trim
  box inset by `safe_area_mm`.
- SVG, PNG, and PDF artwork validation through bundled PyMuPDF.
- QR/barcode expected-value validation through bundled ZXing-C++; SVG and PDF artwork are
  rasterized at 300 DPI before decoding, and a decoder load failure is a validation error
  whenever code validation is requested.
- Operator CLI: validate, package, verify-package, and doctor.
- Immutable-style release directories containing copied artwork, validation report, manifest,
  and SHA-256 checksums.
- Passing and failing SVG/PDF safe-area fixtures plus CLI/package regression tests.
- CI runs the full documented CLI workflow: validate, package, verify-package, and doctor.

## Known external/human blockers

- **TOOL UNAVAILABLE/BLOCKED:** Callas pdfToolbox is not installed or configured. No Callas
  preflight/profile result is claimed.
- No approved production artwork, regulatory-copy source, printer ICC/color target, or
  prepress acceptance profile is in this repository. The software can validate supplied
  specifications, but cannot certify these absent requirements.

## Next operator steps

1. Add approved product specs and both passing/failing artwork fixtures for every SKU.
2. Extend safe-area validation to code positions and non-text/vector artwork where a reliable
   geometry extractor is available.
3. Add the licensed Callas adapter/profile when the printer supplies its preflight target.
4. Run the full verification commands recorded below for each release.

## Verification record

Verified on 2026-08-17 from commit `8885410`:

```text
python3 -m pytest -q                                      # 11 passed
python3 -m ruff check .                                    # passed
python3 -m compileall -q labelos tests                     # passed
python3 -m build --outdir /tmp/labelos-build-safe-area-*   # sdist and wheel created
python3 -m labelos.cli validate examples/label.json --json # passed
python3 -m labelos.cli package examples/label.json ...     # passed
python3 -m labelos.cli verify-package ... --json           # passed
python3 -m labelos.cli doctor --json                       # passed
git diff --check                                           # passed
```

Results: 11 tests passed; Ruff, compile, and whitespace validation passed; the sdist and wheel
were generated at `/tmp/labelos-build-safe-area-9aWdjc`; and the end-to-end package was created
and checksum-verified at `/tmp/labelos-e2e-safe-area-LEuCKj/release`. `doctor` confirmed PyMuPDF
and ZXing-C++ are available; Callas pdfToolbox remains unavailable. QR and Code 128 regression
tests generate raster, SVG, and PDF fixtures and verify their decoded expected values. GitHub
Actions runs tests, lint, build, and the CLI workflow on Python 3.10 and 3.12.
