# Production readiness status

## Implemented

- JSON label specification validation with physical dimensions, bleed, safe-area
  configuration sanity, minimum DPI, and required-copy fields.
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

## Known software release gates

- **Not production-complete on `main`:** `safe_area_mm` is checked for a valid configuration
  value, but current validation does not inspect artwork bounds to prove visible content stays
  inside the safe area. Do not interpret a passing report as a safe-area clearance.
- **In-flight implementations:** the active draft pull requests for artwork safe-area
  enforcement, malformed PDF/PNG rejection, release-manifest hardening, and reusable failing
  fixtures must be reviewed and integrated before claiming production readiness. Avoid creating
  duplicate implementations while those changes remain in review.

## Next operator steps

1. Review and integrate the active software release gates, then run the complete end-to-end
   verification suite against their combined result.
2. Add approved product specs and both passing/failing artwork fixtures for every SKU.
3. Add the licensed Callas adapter/profile when the printer supplies its preflight target.
4. Run the full verification commands recorded below for each release.

## Verification record

Verified on 2026-08-14 from commit `1e86abd08646dfef720fc2f45fa168846527aec5`:

```text
python3 -m pytest -q                      # 9 passed
python3 -m ruff check .                   # passed
python3 -m compileall -q labelos tests    # passed
python3 -m build --outdir /tmp/labelos-build
python3 -m labelos.cli validate examples/label.json --json
python3 -m labelos.cli package examples/label.json /tmp/labelos-current-e2e --json
python3 -m labelos.cli verify-package /tmp/labelos-current-e2e --json
python3 -m labelos.cli doctor --json
python3 -m pip check                       # passed
```

Results: 9 tests passed; Ruff passed; the sdist and wheel were generated in
`/tmp/labelos-build`; and the
end-to-end package was created and checksum-verified at `/tmp/labelos-current-e2e`.
`doctor` confirmed PyMuPDF and ZXing-C++ are available; Callas pdfToolbox remains unavailable.
QR and Code 128 regression tests generate raster, SVG, and PDF fixtures and verify their
decoded expected values. GitHub Actions runs tests, lint, and builds on Python 3.10 and 3.12.
