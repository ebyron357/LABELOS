# Production readiness status

## Implemented

- JSON label specification validation with physical dimensions, bleed, safe-area sanity,
  minimum DPI, and required-copy fields.
- SVG, PNG, and PDF artwork validation through bundled PyMuPDF.
- QR/barcode expected-value validation through bundled ZXing-C++; SVG and PDF artwork are
  rasterized at 300 DPI before decoding, and a decoder load failure is a validation error
  whenever code validation is requested.
- Safe-area validation for SVG, PNG, and PDF: raster content is checked against the
  bleed-plus-safe-area boundary and uncheckable inputs fail closed.
- Operator CLI: validate, package, verify-package, and doctor.
- Immutable-style release directories containing copied artwork, validation report, immutable
  label specification, manifest, SHA-256 checksums, and byte counts. Verification rejects
  path traversal, symlink entries, malformed artifacts, and inconsistent package metadata.
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

Verified on 2026-08-11 from commit `450e9b67491b2b6dc23190cc5ddca6e5e10995f1`:

```text
python3 -m pytest -q                      # 22 passed
python3 -m ruff check .                   # passed
python3 -m compileall -q labelos          # passed
python3 -m build --outdir /tmp/labelos-production-build
python3 -m labelos.cli validate examples/label.json --json
python3 -m labelos.cli package examples/label.json /tmp/labelos-production-e2e --json
python3 -m labelos.cli verify-package /tmp/labelos-production-e2e --json
python3 -m labelos.cli doctor --json
```

Results: 22 tests passed; Ruff and bytecode compilation passed; the sdist and wheel were
generated in `/tmp/labelos-production-build`; and the end-to-end package was created and
verified at `/tmp/labelos-production-e2e`. `doctor` confirmed PyMuPDF and ZXing-C++ are
available; **TOOL UNAVAILABLE/BLOCKED:** Callas pdfToolbox remains unavailable. Regression
tests cover QR and Code 128 decoding for raster/vector artwork, safe-area acceptance and
rejection across SVG/PNG/PDF, malformed vector artwork, and package-tampering checks. GitHub
Actions runs tests, lint, and builds on Python 3.10 and 3.12.
