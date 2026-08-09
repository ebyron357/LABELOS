# Production-readiness status

## Completed in this revision

- Python package and CLI are bootstrapped.
- Strict JSON specifications cover finished dimensions, bleed, trim, safe area, DPI,
  required copy, expected barcode, and expected QR values.
- Raster artwork validation checks physical dimensions, embedded resolution, optional
  color mode, barcode decoding, and QR decoding.
- PDF validation checks page count, physical dimensions, extractable required copy,
  and barcode/QR values decoded from a high-resolution rendering.
- Raster artwork can be exported to a one-page production-size PDF before it enters
  the PDF validation and package workflow.
- Delivery packages include the validated PDF, JSON validation report, specification,
  manifest, and SHA-256 checksum.
- `doctor` reports locally available libraries and explicitly identifies Callas
  pdfToolbox as unavailable rather than claiming an external preflight.
- Tests include success and failure fixtures generated at test runtime, CLI behavior,
  PDF validation, and delivery package creation.

## Known external/human-only blockers

- A licensed Callas pdfToolbox installation and its project-specific profile are
  required before claiming a full commercial prepress preflight.
- Artwork-specific safe-area visual inspection, regulatory-copy rules, brand fonts,
  ICC targets, and press limits require approved production requirements. The software
  does not invent or alter those specifications.

## Next work

1. Add a real external prepress adapter only when its executable/profile and expected
   report format are supplied.
2. Add approved artwork and regulatory rules as explicit specifications; do not infer
   product facts or alter approved copy.

## Latest verification

Commands completed successfully before this status update:

```text
python3 -m pytest                 # 4 passed
python3 -m ruff check .           # all checks passed
python3 -m build                  # sdist and wheel produced
python3 -m labelos.cli doctor     # ZXing-C++ and PyMuPDF available; Callas blocked
```

The test suite exercises decodable Code 128 and QR fixtures, passing and failing
validation paths, PDF verification, package manifests/checksums, and CLI exit codes.
Verified implementation commit: `ee82040` (`feat: add label production validation system`).
