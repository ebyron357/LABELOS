# Production readiness status

## Implemented

- JSON label specification validation with physical dimensions, bleed, safe-area sanity,
  minimum DPI, and required-copy fields.
- SVG, PNG, and PDF artwork validation through bundled PyMuPDF.
- QR/barcode expected-value validation through bundled ZXing-C++; SVG and PDF artwork are
  rasterized at 300 DPI before decoding, and a decoder load failure is a validation error
  whenever code validation is requested.
- Operator CLI: validate, package, verify-package, and doctor.
- Immutable-style release directories containing copied artwork, canonical `label-spec.json`,
  validation report, manifest, and SHA-256 checksums. Verification rejects manifest path
  traversal, malformed entries, byte-count/checksum mismatches, non-passing reports, and specs
  that do not reference the packaged artwork.
- Invalid PDFs produce a structured validation failure rather than crashing the operator CLI.
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
3. Establish approved, format-specific safe-area semantics (including what counts as artwork
   content) before implementing safe-area enforcement; the current `safe_area_mm` check only
   verifies configuration sanity.
4. Run the full verification commands recorded below for each release.

## Verification record

Verified on 2026-08-10 from commit `520f6f3dae30b7b1e9371459ba67736ab0ffd78e`:

```text
python3 -m pytest -v                      # 15 passed
python3 -m ruff check .                   # passed
python3 -m build                          # sdist and wheel created in dist/
python3 -m labelos.cli validate examples/label.json --json
python3 -m labelos.cli package examples/label.json /tmp/labelos-e2e-integrity --json
python3 -m labelos.cli verify-package /tmp/labelos-e2e-integrity --json
python3 -m labelos.cli doctor --json
```

Results: 15 tests passed; Ruff passed; the sdist and wheel were generated in `dist/`; and the
end-to-end package, including `label-spec.json`, was created and checksum-verified at
`/tmp/labelos-e2e-integrity`.
`doctor` confirmed PyMuPDF and ZXing-C++ are available; Callas pdfToolbox remains unavailable.
QR and Code 128 regression tests generate raster, SVG, and PDF fixtures and verify their
decoded expected values. GitHub Actions runs tests, lint, and builds on Python 3.10 and 3.12.
