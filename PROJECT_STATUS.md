# Production readiness status

Canonical implementation: branch `stabilize/canonical-validator`.

LABELOS is a command-line validation and release engine. Operators validate SVG/PNG/PDF
artwork, then create and verify SHA-256 release packages. The HTTP API, Illustrator
bridge, and n8n workflow exist in this repository as **future / optional** automation;
they are **not** required to use LABELOS on production artwork today.

## Capability truth

| Capability | Status |
| --- | --- |
| SVG artwork validation | **AVAILABLE NOW** |
| PNG artwork validation | **AVAILABLE NOW** |
| PDF artwork validation | **AVAILABLE NOW** |
| Malformed artwork fail-closed (SVG/PNG/PDF) | **AVAILABLE NOW** (PNG image data is decoded, not just header-checked; SVG DOCTYPE/entity declarations are rejected) |
| Physical dimensions (trim + bleed) | **AVAILABLE NOW** |
| Trim/bleed expectations | **AVAILABLE NOW** |
| Safe-area enforcement | **AVAILABLE NOW** (visible non-white content vs trim + safe inset) |
| Minimum DPI (PNG effective resolution) | **AVAILABLE NOW** |
| Effective DPI for placed raster assets | **AVAILABLE NOW** (SVG data-URI images and PDF placed images) |
| Required-copy validation | **AVAILABLE NOW** (source-text search; does not OCR outlined/outlined-to-curves copy) |
| QR decoding and expected-value validation | **AVAILABLE NOW** (ZXing-C++; SVG/PDF rasterized at 300 DPI) |
| Barcode decoding and expected-value validation | **AVAILABLE NOW** (includes UPC-A / EAN-13 leading-zero matching) |
| Validation reports | **AVAILABLE NOW** |
| Release package generation | **AVAILABLE NOW** |
| SHA-256 integrity | **AVAILABLE NOW** |
| Manifest validation | **AVAILABLE NOW** |
| Package tamper detection | **AVAILABLE NOW** |
| Unsafe filename/path rejection | **AVAILABLE NOW** |
| Failed-report rejection | **AVAILABLE NOW** |
| Package verification | **AVAILABLE NOW** |
| Dependency/environment diagnostics (`doctor`) | **AVAILABLE NOW** |
| Linked (non-embedded) SVG raster files | **PARTIAL** (data-URI rasters are checked; external `href` files are skipped) |
| Required-copy on outlined text / raster-only type | **PARTIAL** (string must exist in SVG/PDF text extraction) |
| Color management / ICC / overprint | **FUTURE** |
| Callas pdfToolbox / commercial prepress profiles | **EXTERNAL DEPENDENCY** — not licensed, not configured, never faked as PASS (`SKIPPED_NOT_CONFIGURED`) |
| HTTP API / n8n orchestration | **FUTURE** (code exists; not the operator path) |
| Illustrator generation | **FUTURE** (workstation bridge exists; live COM requires Illustrator) |
| Prompt-to-label generation | **FUTURE** |
| Web UI / visual editing | **FUTURE** |
| Brand libraries / SKU templates | **FUTURE** |
| Approval workflows as a product | **FUTURE** |

## Operator path (use this)

```text
python -m pip install -e ".[test,dev]"
labelos doctor --json
labelos validate examples/label.json --json
labelos package examples/label.json storage/demo-release
labelos verify-package storage/demo-release
```

## Known real blockers

1. **Callas / pdfToolbox is unavailable.** LABELOS will not claim commercial preflight PASS.
2. **Required copy is text-extraction based.** Outlined type and rasterized copy are not found.
3. **Safe-area uses rendered occupancy against white.** Full-bleed colored backgrounds can
   be reported as safe-area violations; keep live matter inside the inset.
4. **No approved printer profile is loaded.** Do not invent printer-specific limits.
5. **Live Illustrator generation is blocked** without a licensed workstation and template.

## Future roadmap (documented, not built in this pass)

- Prompt-driven label creation
- Web UI and visual editing
- Brand libraries and SKU templates
- Illustrator generation as a supported production path
- Approval workflows
- Public APIs and automated orchestration

## Superseded overlapping PRs

Do **not** merge the historical hardening swarm. Unique valid behavior from those PRs was
reproduced on `stabilize/canonical-validator`. Close as superseded:

- Malformed-PDF fail-closed: #120, #121, #122, #124
- PDF embedded-image DPI: #109, #113, #129, #133
- SVG embedded-raster DPI: #114
- Safe-area enforcement: #84–#88, #91–#94, #101, #103–#108, #111, #115–#117, #128
- Package verification hardening: #96–#100, #102, #110, #112, #119, #123, #130, #133
- Generic “harden label production validation” duplicates: #85, #90, #95, #118, #125–#127, #131, #132
- Broader duplicates in the same series: #7–#83 with the same titles

Keep `main` (#6 and earlier) as history. `feat/production-label-automation` remains the
optional API/bridge lineage; it is not the operator-facing product.

## Verification record

Verified on 2026-08-18 from branch `stabilize/canonical-validator`:

```text
python -m pytest -q                      # 52 passed
python -m ruff check .                   # passed
python -m compileall -q labelos illustrator_bridge tests
python -m pip check                      # passed
python -m build                          # sdist and wheel in dist/
labelos doctor --json                    # Callas SKIPPED_NOT_CONFIGURED
labelos validate examples/label.json --json          # PASS
labelos validate examples/failing-label.json --json  # REQUIRED_COPY_MISSING
labelos package examples/label.json storage/demo-release
labelos verify-package storage/demo-release          # PASS
# after tampering artwork: checksum + byte-count mismatch, FAIL
```

Callas pdfToolbox remains unavailable and is never reported as PASS.
