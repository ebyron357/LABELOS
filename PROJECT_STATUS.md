# Production readiness status

## Implemented

- JSON label specification validation with physical dimensions, bleed, safe-area sanity,
  minimum DPI, and required-copy fields.
- SVG, PNG, and PDF artwork validation through bundled PyMuPDF.
- Safe-area enforcement for SVG, PNG, and PDF artwork: uniform full-bleed backgrounds are
  permitted; non-background pixels in the bleed-plus-safe-area margin fail validation.
- QR/barcode expected-value validation through bundled ZXing-C++; SVG and PDF artwork are
  rasterized at 300 DPI before decoding, and a decoder load failure is a validation error
  whenever code validation is requested.
- Operator CLI: validate, package, verify-package, and doctor.
- Immutable-style release directories containing copied artwork, a portable serialized label
  specification, validation report, manifest, SHA-256 checksums, and byte counts. Verification
  rejects tampering, unexpected files, non-passing reports, and invalid spec-to-artwork bindings.
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

Verified on 2026-08-15 from commit `d058be2963599f99201cb023284f0de2d1931d95`:

```text
python3 -m pytest -q                      # 12 passed
python3 -m ruff check .                   # passed
python3 -m compileall -q labelos tests    # passed
python3 -m pip check                      # passed
python3 -m build --outdir /tmp/labelos-production-build
python3 -m labelos.cli validate examples/label.json --json
python3 -m labelos.cli package examples/label.json /tmp/labelos-production-e2e-Ulpi0R/release --json
python3 -m labelos.cli verify-package /tmp/labelos-production-e2e-Ulpi0R/release --json
python3 -m labelos.cli doctor --json
```

Results: 12 tests passed; Ruff, bytecode compilation, and dependency checks passed; the sdist and
wheel were generated in `/tmp/labelos-production-build`; and the end-to-end package was created
and checksum-verified at `/tmp/labelos-production-e2e-Ulpi0R/release`. `doctor` confirmed
PyMuPDF and ZXing-C++ are available; Callas pdfToolbox remains TOOL UNAVAILABLE/BLOCKED. QR and
Code 128 regression tests generate raster, SVG, and PDF fixtures and verify their decoded expected
values. GitHub Actions runs tests, lint, and builds on Python 3.10 and 3.12.
