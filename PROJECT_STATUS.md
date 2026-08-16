# Production readiness status

## Implemented

- JSON label specifications validate dimensions, bleed, safe-area sanity, minimum DPI, and
  required copy.
- SVG, PNG, and PDF artwork validation includes dimensions, PNG raster resolution, PDF
  readability/font metadata, and expected QR/barcode decoding through ZXing-C++.
- Configured safe areas are enforced. PNG is inspected directly; SVG/PDF are rasterized at
  300 DPI. Content inside `bleed_mm + safe_area_mm` fails with `SAFE_AREA_VIOLATION`.
  Transparent artwork and non-uniform edge backgrounds fail closed as
  `SAFE_AREA_UNCHECKABLE`.
- The operator CLI provides `validate`, `package`, `verify-package`, and `doctor`.
- Release packages use schema v2 and include copied artwork, a validation report, byte sizes,
  SHA-256 checksums, and the validated spec. Verification rejects unsafe paths, symlinks,
  unexpected files, malformed/non-passing reports, checksum mismatches, and byte-size
  mismatches.
- Regression tests cover successful and failing dimensions, copy, safe-area, code decode,
  package integrity, CLI, PNG/SVG/PDF code decoding, unsafe manifest paths, and unexpected
  package files.

## Known external/human blockers

- **TOOL UNAVAILABLE/BLOCKED:** Callas pdfToolbox is not installed or configured. No Callas
  preflight/profile result is claimed.
- No approved production artwork, regulatory-copy source, printer ICC/color target, or
  prepress acceptance profile is in this repository. The software validates supplied
  specifications but cannot certify these absent requirements.

## Next operator steps

1. Supply approved specs and passing/failing artwork fixtures for every SKU.
2. Add a licensed Callas adapter/profile after the printer provides its preflight target.
3. Run the verification commands below for every release candidate.

## Verification record

Verified on 2026-08-16 from implementation commit
`0908bf04f35e92327dbd0254e91d821e98b47a40`:

```text
python3 -m pytest -q --cache-clear                         # 14 passed
python3 -m ruff check .                                    # passed
python3 -m compileall -q labelos tests                     # passed
python3 -m build --outdir /tmp/labelos-package-v2-build    # sdist + wheel created
python3 -m labelos.cli validate examples/label.json --json # passed
python3 -m labelos.cli package examples/label.json /tmp/labelos-package-v2 --json
python3 -m labelos.cli verify-package /tmp/labelos-package-v2 --json
python3 -m labelos.cli doctor --json
```

The end-to-end release package at `/tmp/labelos-package-v2` was created and verified. Doctor
reported PyMuPDF and ZXing-C++ available; Callas pdfToolbox remains unavailable. GitHub Actions
runs tests, lint, and builds on Python 3.10 and 3.12.
