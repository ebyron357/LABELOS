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
  byte counts, and SHA-256 checksums. Verification rejects malformed schemas and paths that
  escape the package directory.
- Passing fixture coverage plus CLI/package regression tests. Generated tests exercise
  barcode and QR success/failure paths; committed operator-facing failing fixtures are pending.

## Known external/human blockers

- **TOOL UNAVAILABLE/BLOCKED:** Callas pdfToolbox is not installed or configured. No Callas
  preflight/profile result is claimed.
- No approved production artwork, regulatory-copy source, printer ICC/color target, or
  prepress acceptance profile is in this repository. The software can validate supplied
  specifications, but cannot certify these absent requirements.

## Next operator steps

1. Define approved `trim_mm` semantics and safe-area object-bound rules, then implement
   format-specific release gates. Current `safe_area_mm` checking is configuration sanity only;
   `trim_mm` is recorded but not used in artwork-dimension math.
2. Add approved product specs and both passing/failing artwork fixtures for every SKU.
3. Add the licensed Callas adapter/profile when the printer supplies its preflight target.
4. Run the full verification commands recorded below for each release.

## Verification record

Verified on 2026-08-14 for code changes committed in
`9fde3d03243c83d6a94dc2330a5420d52604f8aa`:

```text
python3 -m pytest -q                      # 10 passed
python3 -m ruff check .                   # passed
python3 -m build --outdir /tmp/labelos-build-20260814-manifest
python3 -m labelos.cli validate examples/label.json --json
python3 -m labelos.cli package examples/label.json /tmp/labelos-e2e-20260814-manifest/release --json
python3 -m labelos.cli verify-package /tmp/labelos-e2e-20260814-manifest/release --json
python3 -m labelos.cli doctor --json
```

Results: 10 tests passed; Ruff passed; and the sdist and wheel were generated at
`/tmp/labelos-build-20260814-manifest`. The CLI workflow validated and packaged the example
at `/tmp/labelos-e2e-20260814-manifest.hvPxM5/release`, then checksum-verified it. It also
rejected a manifest containing an artwork path of `../outside.svg`. `doctor` confirmed PyMuPDF
and ZXing-C++ are available; Callas pdfToolbox remains unavailable. QR and Code 128 regression
tests generate raster, SVG, and PDF fixtures and verify decoded expected values. GitHub Actions
runs tests, lint, and builds on Python 3.10 and 3.12.
