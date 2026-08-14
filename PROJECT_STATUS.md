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
  and SHA-256 checksums.
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

## Current run and next task

On 2026-08-14, commit `ec73956` closed a release-gate gap: a PNG with a valid signature and
header dimensions but truncated content now fails closed with `PNG_INVALID`. The regression test
and CLI check both cover this case.

Active independent pull requests implement safe-area enforcement, malformed-PDF fail-closed
handling, manifest hardening, and reusable failing fixtures. Do not duplicate those changes.
After those pull requests are merged, run the complete verification below on their combined
result before declaring the software work complete.

## Verification record

Verified on 2026-08-14 from commit `ec73956`:

```text
python3 -m pytest -q                                      # 10 passed
python3 -m ruff check .                                    # passed
python3 -m compileall -q labelos                           # passed
python3 -m pip check                                       # passed
python3 -m build --outdir /tmp/labelos-build               # sdist and wheel created
python3 -m labelos.cli validate examples/label.json --json # passed
python3 -m labelos.cli package examples/label.json /tmp/labelos-png-hardening-e2e --json
python3 -m labelos.cli verify-package /tmp/labelos-png-hardening-e2e --json
python3 -m labelos.cli doctor --json                       # passed
```

Results: 10 tests passed; Ruff, bytecode compilation, dependency validation, and package build
passed. The end-to-end package was created and checksum-verified at
`/tmp/labelos-png-hardening-e2e`; a deliberately truncated PNG returned `PNG_INVALID` and CLI
exit status 1.
`doctor` confirmed PyMuPDF and ZXing-C++ are available; Callas pdfToolbox remains unavailable.
QR and Code 128 regression tests generate raster, SVG, and PDF fixtures and verify their
decoded expected values. GitHub Actions runs tests, lint, and builds on Python 3.10 and 3.12.
