# Production readiness status

## Implemented

- JSON label specification validation with physical dimensions, bleed, safe-area sanity,
  minimum DPI, and required-copy fields.
- SVG, PNG, and PDF artwork validation through bundled PyMuPDF.
- QR/barcode expected-value validation through bundled ZXing-C++; SVG and PDF artwork are
  rasterized at 300 DPI before decoding, and a decoder load failure is a validation error
  whenever code validation is requested.
- Operator CLI: validate, package, verify-package, and doctor.
- Immutable-style schema-v2 release directories containing copied artwork, a normalized label
  specification, passing validation report, SHA-256 checksums, and byte counts. Verification
  rejects untracked files, symlinks, unsafe manifest names, invalid report/spec bindings, and
  mismatched artifact metadata.
- Passing and failing fixture coverage plus CLI/package regression tests.
- Invalid PDF input is reported as `PDF_INVALID` rather than escaping the operator CLI.

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

Verified on 2026-08-15 from the working tree based on commit
`1e86abd9dc5cc60508c4a4d51475575be778647b`:

```text
python3 -m pytest -q                      # 11 passed
python3 -m ruff check .                   # passed
python3 -m compileall -q labelos          # passed
python3 -m build --outdir /tmp/labelos-production-build  # sdist and wheel created
python3 -m labelos.cli validate examples/label.json --json
python3 -m labelos.cli package examples/label.json /tmp/labelos-e2e/release --json
python3 -m labelos.cli verify-package /tmp/labelos-e2e/release --json
python3 -m labelos.cli doctor --json
python3 -m pip check                      # passed
```

Results: 11 tests passed; Ruff, bytecode compilation, dependency health, and the build passed;
and the end-to-end package was created and fully verified at a temporary
`/tmp/labelos-e2e-*/release` path.
`doctor` confirmed PyMuPDF and ZXing-C++ are available; Callas pdfToolbox remains unavailable.
QR and Code 128 regression tests generate raster, SVG, and PDF fixtures and verify their
decoded expected values. GitHub Actions runs tests, lint, and builds on Python 3.10 and 3.12.
