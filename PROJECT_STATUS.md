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
- Native-build evidence gate (`labelos/evidence.py`): verifies operator-supplied evidence JSON,
  build log, preview, and native artwork; enforces empty `missing_layers` plus positive
  confirmation of required layers and named objects; requires `reopened_without_repair` to be
  literally `true`; requires the log's final non-empty line to be exactly `PASSED`; and rejects
  absolute, escaping, or symlinked evidence paths. Every failure blocks packaging.
- Evidence packaging into `native-evidence/` with SHA-256 and byte counts taken from the copied
  bytes, plus independent re-verification and tamper detection in `verify-package`.
- `blocked_requirements` recorded on every manifest and re-checked during verification.
- Passing and failing fixture coverage plus CLI/package regression tests.

## Known external/human blockers

- **TOOL UNAVAILABLE/BLOCKED:** Callas pdfToolbox is not installed or configured. No Callas
  preflight/profile result is claimed.
- No approved production artwork, regulatory-copy source, printer ICC/color target, or
  prepress acceptance profile is in this repository. The software can validate supplied
  specifications, but cannot certify these absent requirements.
- **EVIDENCE NOT SUPPLIED:** No real native-application run exists in this repository. The
  `.ai` source, exported preview, evidence JSON, and build log for any specific label remain
  operator-side. The test suite builds synthetic bundles in temporary directories to exercise
  the gate; those are test fixtures and are never production evidence.
- A passing evidence gate resolves none of the four `blocked_requirements`. Printer profile,
  ICC profile, regulatory approval, and production PDF must each be independently supplied and
  approved before any label is production-approved.

## Next operator steps

1. Add approved product specs and both passing/failing artwork fixtures for every SKU.
2. Add the licensed Callas adapter/profile when the printer supplies its preflight target.
3. Run the full verification commands recorded below for each release.

## Verification record

Verified on 2026-08-15 from commit `1e86abd` on Python 3.11.15:

```text
python3 -m pytest                         # 56 passed
python3 -m ruff check .                   # All checks passed
python3 -m build                          # sdist and wheel created in dist/
python3 -m labelos.cli validate examples/label.json --json
python3 -m labelos.cli package examples/label.json /tmp/labelos-e2e --json
python3 -m labelos.cli verify-package /tmp/labelos-e2e --json
python3 -m labelos.cli doctor --json
```

Results: 56 tests passed and Ruff passed. `doctor` confirmed PyMuPDF and ZXing-C++ are
available; Callas pdfToolbox remains unavailable. QR and Code 128 regression tests generate
raster, SVG, and PDF fixtures and verify their decoded expected values. GitHub Actions runs
tests, lint, and builds on Python 3.10 and 3.12.

The evidence gate was additionally exercised end-to-end through the CLI against a 25-case
falsification matrix (absent, malformed, and non-object evidence JSON; each artifact removed;
`missing_layers` omitted, non-empty, and wrong-typed; unconfirmed required layers and objects;
`reopened_without_repair` false, omitted, `"true"`, and `1`; empty, blank, `FAILED`, and
lowercase logs; traversal, absolute, and symlinked paths; typo'd field names). Every case
failed closed with no package directory created. An 18-case tamper matrix against a built
package confirmed `verify-package` detects altered, deleted, added, symlinked, and
manifest-rewritten evidence, and rejects any manifest whose `blocked_requirements` list is
emptied, shortened, or replaced.

**CodeQL was not run: the `codeql` CLI is not installed in this environment and no CodeQL
workflow exists in this repository.** No static security scanner beyond Ruff was available.

Package hashes are stored in the manifest they protect, so they detect corruption and partial
tampering but not a wholesale rewrite of the package by an actor with write access. Detached
signing is not implemented.
