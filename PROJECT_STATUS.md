# Production readiness status

## Implemented

- JSON label specification validation with physical dimensions, bleed, safe-area sanity,
  minimum DPI, and required-copy fields.
- SVG, PNG, and PDF artwork validation through bundled PyMuPDF.
- QR/barcode expected-value validation through bundled ZXing-C++; SVG and PDF artwork are
  rasterized at 300 DPI before decoding, and a decoder load failure is a validation error
  whenever code validation is requested.
- Operator CLI: validate, package, verify-package, and doctor.
- Immutable-style release directories containing copied artwork, normalized label specification,
  validation report, manifest, SHA-256 checksums, and byte counts. Package verification rejects
  unexpected/non-regular files, unsafe manifest paths, invalid artwork bindings, and reports that
  do not record a pass.
- Invalid PDFs fail closed with `PDF_INVALID` instead of escaping the operator CLI.
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
3. Supply a governing definition of which artwork objects constitute critical safe-area content;
   generic raster/PDF inspection cannot infer that distinction without rejecting valid full-bleed
   artwork.
4. Run the full verification commands recorded below for each release.

## Verification record

Verified on 2026-08-09 from commit `0fbe2c760154c772e2eb424971b882ce52919874`:

```text
python3 -m pytest                         # 9 passed
python3 -m ruff check .                   # passed
python3 -m build                          # sdist and wheel created in dist/
python3 -m labelos.cli validate examples/label.json --json
python3 -m labelos.cli package examples/label.json /tmp/labelos-e2e --json
python3 -m labelos.cli verify-package /tmp/labelos-e2e --json
python3 -m labelos.cli doctor --json
```

Results: 9 tests passed; Ruff passed; the sdist and wheel were generated in `dist/`; and the
end-to-end package was created and checksum-verified at `/tmp/labelos-e2e`.
`doctor` confirmed PyMuPDF and ZXing-C++ are available; Callas pdfToolbox remains unavailable.
QR and Code 128 regression tests generate raster, SVG, and PDF fixtures and verify their
decoded expected values. GitHub Actions runs tests, lint, and builds on Python 3.10 and 3.12.

Verified on 2026-08-15 from a working tree based on `1e86abd08646dfef720fc2f45fa168846527aec5`:

```text
python3 -m pytest -q                      # 12 passed
python3 -m ruff check .                   # passed
python3 -m compileall -q labelos          # passed
python3 -m build --outdir /tmp/labelos-production-build  # sdist and wheel created
python3 -m labelos.cli validate examples/label.json --json  # passed
python3 -m labelos.cli package examples/label.json /tmp/labelos-production-e2e --json  # passed
python3 -m labelos.cli verify-package /tmp/labelos-production-e2e --json  # passed
python3 -m labelos.cli doctor --json      # PyMuPDF/ZXing available; Callas unavailable
python3 -m pip check                      # no broken requirements
```
