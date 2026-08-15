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

### Native-build evidence

A label may additionally declare an optional `native_evidence` block recording proof that a
native application build produced the artwork. LABELOS **verifies** that evidence; it never
generates it. All paths are relative to the configuration file's directory.

```json
{
  "native_evidence": {
    "evidence_json": "evidence.json",
    "log": "build.log",
    "preview_png": "preview.png",
    "native_artwork": "source.ai",
    "required_layers": ["Dieline", "Artwork"],
    "required_objects": ["dieline_path"]
  }
}
```

`evidence_json` and `log` are required whenever the block is present; `preview_png` and
`native_artwork` are optional, but any artifact that is declared must exist and is packaged.
The referenced `evidence_json` must be a JSON object recording `missing_layers` (present and
empty), `layers` (positively confirming every `required_layers` entry), `named_objects`
(confirming every `required_objects` entry), and `reopened_without_repair` set to boolean
`true`. The log's final non-empty line must be exactly `PASSED`.

The gate fails closed. Any of the following is a validation error that blocks packaging:

| Code | Condition |
| --- | --- |
| `EVIDENCE_ARTIFACT_MISSING` | A required artifact is undeclared or does not exist |
| `EVIDENCE_INVALID_JSON` | Evidence JSON is unreadable, malformed, or not an object |
| `NATIVE_LAYERS_MISSING` | `missing_layers` absent/non-empty, or a required layer unconfirmed |
| `NAMED_OBJECTS_MISSING` | A required named object is not confirmed present |
| `NATIVE_REOPEN_UNPROVEN` | `reopened_without_repair` is not literally `true` |
| `EVIDENCE_LOG_NOT_PASSED` | The log's final non-empty line is not exactly `PASSED` |
| `EVIDENCE_PATH_UNSAFE` | An artifact path is absolute, escapes the config directory, or is a symlink |

Truthy stand-ins are rejected: `"true"`, `1`, and a non-empty `missing_layers` all fail. A
passing gate means the evidence was supplied and is internally consistent — nothing more.

Artwork dimensions include bleed: the example above expects a 106 × 56 mm asset. SVG, PNG,
and PDF artwork are accepted. PDF inspection and QR/barcode decoding are installed with
LABELOS; SVG and PDF are rendered at 300 DPI before code decoding. If `barcode_value` or
`qr_value` is configured but the decoder cannot load, validation fails rather than asserting a
code was checked.

## Commands

- `labelos validate CONFIG [--json]`: validate format, dimensions, raster resolution,
  required copy, and configured barcode/QR values.
- `labelos package CONFIG DESTINATION`: validates, then writes artwork, a JSON validation
  report, and a SHA-256 manifest. Existing package destinations are never overwritten.
  Declared native evidence is copied into `native-evidence/` and the manifest records the
  SHA-256 and byte count of the *copied* bytes. The evidence gate is re-run at package time,
  so a report that never ran it cannot smuggle unverified artifacts into a release.
- `labelos verify-package DESTINATION`: recomputes every hash from the bytes actually present
  in the package, rejects manifest paths that escape the package or resolve through symlinks,
  flags unrecorded files in `native-evidence/`, and confirms the manifest still lists every
  external blocker.
- `labelos doctor`: reports optional validator availability. Callas pdfToolbox is explicitly
  reported as unavailable until a real adapter and licensed profile are configured.

## Current scope and limitations

The core validator provides reproducible local checks and package integrity. Commercial
prepress profiles, approved regulatory copy, brand artwork, printer-specific color targets,
and a Callas adapter are not present in this repository; they must be supplied and approved
by the appropriate owner before a particular label can be certified for print.

Every manifest records `blocked_requirements` — `icc_profile`, `printer_profile`,
`production_pdf`, `regulatory_approval` — and `verify-package` fails if that list is altered
or emptied. **A passing native-evidence gate does not clear any of them.** LABELOS validates
and checksums supplied evidence; it does not produce artwork, regulatory approval, printer
requirements, ICC profiles, or a production-ready PDF, and no PDF/X-1a generation path exists
in this repository.

Package integrity is self-contained: hashes live in the same manifest they protect, so they
detect accidental corruption and partial tampering, but an actor who can rewrite the whole
package can also rewrite the manifest. Detached signing or an external hash record is
required to defend against that, and is not implemented here.
