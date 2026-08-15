# Production readiness status

## Implemented

- JSON label specification validation with physical dimensions, bleed, safe-area sanity,
  minimum DPI, and required-copy fields.
- SVG, PNG, and PDF artwork validation through bundled PyMuPDF.
- Safe-area enforcement for PNG, SVG, and PDF artwork. Vector assets are rendered at 300 DPI;
  uniform corner-sampled canvas backgrounds are excluded while visible marks must remain inside
  the configured trim-safe bounds.
- QR/barcode expected-value validation through bundled ZXing-C++; SVG and PDF artwork are
  rasterized at 300 DPI before decoding, and a decoder load failure is a validation error
  whenever code validation is requested.
- Operator CLI: validate, package, verify-package, and doctor.
- Immutable-style release directories containing copied artwork, validation report, manifest,
  canonical `label-spec.json`, SHA-256 checksums, and byte counts. Verification rejects malformed
  manifests, traversal paths, duplicate or symbolic-link artifacts, hash/size mismatches, failed
  reports, and mismatched report/spec/manifest data.
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

Verified on 2026-08-15 from the production-readiness working tree:

```text
python3 -m pytest -q                      # 14 passed
python3 -m ruff check .                   # passed
python3 -m compileall -q labelos tests    # passed
python3 -m pip check                      # no broken requirements
python3 -m build --outdir /tmp/labelos-production-build
python3 -m labelos.cli validate examples/label.json --json
python3 -m labelos.cli package examples/label.json /tmp/labelos-production-e2e --json
python3 -m labelos.cli verify-package /tmp/labelos-production-e2e --json
python3 -m labelos.cli doctor --json
```

Results: 14 tests passed; Ruff, bytecode compilation, package build, and dependency checks
passed. The sdist and wheel were generated in `/tmp/labelos-production-build`; the end-to-end
package was created and checksum-verified at `/tmp/labelos-production-e2e`. Regression coverage
includes valid and invalid safe-area PNGs, malformed PDFs, unsafe/duplicate manifest entries, and
symbolic-link artifacts.
`doctor` confirmed PyMuPDF and ZXing-C++ are available; Callas pdfToolbox remains unavailable.
QR and Code 128 regression tests generate raster, SVG, and PDF fixtures and verify their
decoded expected values. GitHub Actions runs tests, lint, and builds on Python 3.10 and 3.12.
