# LABELOS

LABELOS validates packaging-label artwork before it is released to production and creates
checksummed release packages. It deliberately fails closed: an unavailable required decoder
or an invalid artwork check prevents packaging.

## Quick start

```bash
python -m pip install -e .
labelos validate examples/label.json
labelos package examples/label.json dist/example-label
labelos verify-package dist/example-label
labelos doctor
```

The configuration is JSON:

```json
{
  "artwork": "label.pdf",
  "width_mm": 100,
  "height_mm": 50,
  "bleed_mm": 3,
  "safe_area_mm": 2,
  "min_dpi": 300,
  "required_copy": ["Product name", "NET 250 g"],
  "barcode_value": "0123456789012",
  "qr_value": "https://example.com/product"
}
```

Artwork dimensions include bleed: the example above expects a 106 × 56 mm asset. SVG, PNG,
and PDF artwork are accepted. PDF inspection and QR/barcode decoding are installed with
LABELOS; SVG and PDF are rendered at 300 DPI before code decoding. If `barcode_value` or
`qr_value` is configured but the decoder cannot load, validation fails rather than asserting a
code was checked.

## Native-build evidence

A label configuration may carry an optional `native_evidence` block. It records that a
native (Illustrator) build was produced and inspected by an operator. LABELOS does not
perform that build: it only verifies the evidence the operator supplies, and it fails closed
whenever that evidence is absent, unreadable, malformed, incomplete, or unproven.

```json
{
  "native_evidence": {
    "evidence_json": "evidence/build.json",
    "log": "evidence/build.log",
    "preview_png": "evidence/preview.png",
    "native_artwork": "evidence/label.ai",
    "required_layers": ["Dieline", "Regulatory"],
    "required_objects": ["net_weight_box"]
  }
}
```

All four artifact paths are required once the block exists, and each must be a relative path
that stays inside the configuration directory and does not resolve through a symbolic link.
The evidence JSON must be a JSON object that positively proves the build:

```json
{
  "missing_layers": [],
  "layers": {"Dieline": true, "Regulatory": true},
  "objects": ["net_weight_box"],
  "reopened_without_repair": true
}
```

`layers` and `objects` may be a list of names or a mapping of name to boolean; only entries
explicitly set to boolean `true` count as present. The evidence log must have `PASSED` as its
final non-empty line. Failures are reported as:

| Code | Raised when |
| --- | --- |
| `EVIDENCE_ARTIFACT_MISSING` | A required artifact is undeclared or not on disk |
| `EVIDENCE_PATH_UNSAFE` | A path is absolute, escapes the config directory, or is a symlink |
| `EVIDENCE_INVALID_JSON` | Evidence JSON is unreadable, malformed, or not an object |
| `NATIVE_LAYERS_MISSING` | `missing_layers` is absent, malformed, or non-empty; or a required layer is not positively confirmed |
| `NAMED_OBJECTS_MISSING` | A required named object is not positively confirmed |
| `NATIVE_REOPEN_UNPROVEN` | `reopened_without_repair` is not boolean `true` |
| `EVIDENCE_LOG_NOT_PASSED` | The log is empty or its final non-empty line is not `PASSED` |

A passing gate copies the evidence into `native-evidence/<role>/` inside the release package
and records the SHA-256 and byte count of the **packaged** bytes in `manifest.json`.
`verify-package` re-hashes those bytes, rejects unsafe manifest paths, duplicate or
incomplete entries, symlinks, and any evidence file that is not recorded in the manifest.

**A passing evidence gate is not production approval.** Every manifest records
`blocked_requirements` — `printer_profile`, `icc_profile`, `regulatory_approval`, and
`production_pdf` — and passing native evidence never clears them.

## Commands

- `labelos validate CONFIG [--json]`: validate format, dimensions, raster resolution,
  required copy, and configured barcode/QR values.
- `labelos package CONFIG DESTINATION`: validates, then writes artwork, a JSON validation
  report, and a SHA-256 manifest. Existing package destinations are never overwritten.
- `labelos verify-package DESTINATION`: verifies package checksums.
- `labelos doctor`: reports optional validator availability. Callas pdfToolbox is explicitly
  reported as unavailable until a real adapter and licensed profile are configured.

## Current scope and limitations

The core validator provides reproducible local checks and package integrity. Commercial
prepress profiles, approved regulatory copy, brand artwork, printer-specific color targets,
and a Callas adapter are not present in this repository; they must be supplied and approved
by the appropriate owner before a particular label can be certified for print.

LABELOS records and verifies native-build evidence; it does not produce it. It cannot
generate Illustrator artwork, Illustrator logs, layer or named-object results,
reopen-without-repair proof, regulatory approval, printer requirements, ICC profiles, or a
production-ready PDF, and no PDF/X-1a generation path exists here.

Package integrity is checksum-based, not signed. `verify-package` detects modified, deleted,
added, relinked, or unrecorded package contents, and cross-checks `manifest.json` against the
digests in the packaged validation report. It cannot detect an attacker who rewrites the
manifest and the validation report consistently; that requires a signing key, which this
repository deliberately does not hold.
