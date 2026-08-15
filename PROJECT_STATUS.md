# Production readiness status

## Implemented

- JSON label specification validation with physical dimensions, bleed, safe-area sanity,
  minimum DPI, and required-copy fields.
- SVG, PNG, and PDF artwork validation through bundled PyMuPDF.
- QR/barcode expected-value validation through bundled ZXing-C++; SVG and PDF artwork are
  rasterized at 300 DPI before decoding, and a decoder load failure is a validation error
  whenever code validation is requested.
- Native-build evidence gate (`labelos/evidence.py`) for the optional `native_evidence`
  configuration block. It fails closed on a missing or undeclared artifact, an unsafe path,
  unreadable or malformed evidence JSON, absent/malformed/non-empty `missing_layers`, a
  required layer or named object that is not positively confirmed, `reopened_without_repair`
  that is not boolean `true`, and a log whose final non-empty line is not `PASSED`.
- Evidence packaging into `native-evidence/<role>/` with SHA-256 and byte counts taken from
  the packaged bytes, tied back to the digests recorded at validation time.
- `verify-package` re-hashes packaged bytes and rejects unsafe manifest paths, duplicate or
  incomplete evidence entries, symlinked package contents, evidence files absent from the
  manifest, and a manifest that disagrees with the packaged validation report.
- Operator CLI: validate, package, verify-package, and doctor.
- Immutable-style release directories containing copied artwork, validation report, manifest,
  and SHA-256 checksums. A failed package attempt removes its partial directory.

## Known external/human blockers

These are recorded on every manifest as `blocked_requirements` and are **never** cleared by a
passing native-evidence gate:

- `printer_profile` — not supplied.
- `icc_profile` — not supplied.
- `regulatory_approval` — not supplied.
- `production_pdf` — not supplied. No PDF/X-1a generation path exists in this repository.

Additionally:

- **TOOL UNAVAILABLE/BLOCKED:** Callas pdfToolbox is not installed or configured. No Callas
  preflight/profile result is claimed.
- The Illustrator-native build remains operator-side. This repository contains no real `.ai`
  artwork, preview `.png`, evidence `.json`, Illustrator log, layer result, named-object
  result, or reopen-without-repair proof, and does not fabricate them. The evidence artifacts
  used by the test suite are synthetic fixtures written into a temporary directory; they are
  not production evidence.
- Package integrity is checksum-based, not signed. A consistent rewrite of both
  `manifest.json` and `validation-report.json` cannot be detected without a signing key.

## Next operator steps

1. Run the Illustrator-native build and supply the real evidence set, then validate it.
2. Add approved product specs and both passing/failing artwork fixtures for every SKU.
3. Add the licensed Callas adapter/profile when the printer supplies its preflight target.
4. Obtain the four blocked external approvals independently. A LABELOS pass is not one.

## Verification record

Verified on 2026-08-15 on branch `claude/labelos-evidence-verification-mi6sjm`:

```text
python3 -m pytest                         # 92 passed
python3 -m ruff check .                   # All checks passed
python3 -m bandit -r labelos              # No issues identified
python3 -m build                          # sdist and wheel created in dist/
python3 -m labelos.cli validate CONFIG --json
python3 -m labelos.cli package CONFIG DEST --json
python3 -m labelos.cli verify-package DEST --json
python3 -m labelos.cli doctor --json
```

Results: 92 tests passed; Ruff passed; Bandit reported no issues across 823 lines; the sdist
and wheel were generated in `dist/`. An end-to-end CLI run over a synthetic evidence set
returned exit 0 for validate/package/verify-package, exit 1 with
`EVIDENCE_LOG_NOT_PASSED`/`NATIVE_REOPEN_UNPROVEN` for defective evidence with no package
directory created, and exit 1 with a checksum mismatch after the packaged evidence was
modified. `doctor` confirmed PyMuPDF and ZXing-C++ are available; Callas pdfToolbox remains
unavailable. GitHub Actions runs tests, lint, and builds on Python 3.10 and 3.12.

CodeQL is **not available** in this workspace; no CodeQL result is claimed. Bandit was run as
a substitute static security scan.
