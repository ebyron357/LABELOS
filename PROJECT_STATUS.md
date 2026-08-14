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
- Passing baseline artwork plus reusable failing dimensions and required-copy fixture
  configurations, covered by validator and CLI regression tests.

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

## In-flight repository work

- Active draft PRs address safe-area bounds enforcement ([#51](https://github.com/ebyron357/LABELOS/pull/51)),
  malformed-PDF fail-closed behavior ([#53](https://github.com/ebyron357/LABELOS/pull/53)), and
  release-manifest hardening ([#52](https://github.com/ebyron357/LABELOS/pull/52)). They are not
  included in this branch's baseline and should not be duplicated by later autonomous runs.

## Verification record

Latest verification completed on 2026-08-14 from implementation commit
`9d68a5a3f3e84ce08f82706ddbcf0b9177b842bd`:

```text
python3 -m pytest -q                      # 10 passed
python3 -m ruff check .                   # passed
python3 -m compileall -q labelos          # passed
python3 -m pip check                      # passed
python3 -m build --outdir /tmp/labelos-fixture-build
python3 -m labelos.cli validate examples/label.json --json
python3 -m labelos.cli validate fixtures/failing-dimensions.json --json  # exits 1
python3 -m labelos.cli validate fixtures/failing-required-copy.json --json  # exits 1
python3 -m labelos.cli package examples/label.json /tmp/labelos-fixture-e2e --json
python3 -m labelos.cli verify-package /tmp/labelos-fixture-e2e --json
python3 -m labelos.cli doctor --json
```

Results: 10 tests passed; Ruff, bytecode compilation, dependency checks, and the build passed.
The sdist and wheel were generated in `/tmp/labelos-fixture-build`; the end-to-end package was
created and checksum-verified at `/tmp/labelos-fixture-e2e`. The committed dimensions and
required-copy fixtures each returned their expected validation error and exit code 1.
`doctor` confirmed PyMuPDF and ZXing-C++ are available; Callas pdfToolbox remains unavailable.
QR and Code 128 regression tests generate raster, SVG, and PDF fixtures and verify their
decoded expected values. GitHub Actions runs tests, lint, and builds on Python 3.10 and 3.12.
