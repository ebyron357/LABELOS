# Troubleshooting

| Symptom | Likely cause | Action |
| --- | --- | --- |
| `ERROR: Configuration file does not exist` | Wrong path to JSON spec | Use a path relative to the current directory |
| `ARTWORK_MISSING` | Artwork path in the spec is wrong | Paths are resolved relative to the spec file |
| `DIMENSIONS_MISMATCH` | File size is not trim + bleed | Measure the file; include bleed in the artwork |
| `DPI_TOO_LOW` / `PDF_IMAGE_DPI_TOO_LOW` / `SVG_EMBEDDED_IMAGE_DPI_TOO_LOW` | Placed raster is too small | Increase pixel dimensions or reduce placed size |
| `SVG_LINKED_IMAGE_DPI_TOO_LOW` | Local SVG-linked raster is too small | Increase pixel dimensions or reduce placed size |
| `SVG_LINKED_IMAGE_INSPECTION_FAILED` | Linked SVG image is remote, unsafe, missing, unreadable, or a symlink | Use a regular raster file below the SVG directory and a relative `href` |
| `SAFE_AREA_VIOLATION` | Live matter in the bleed/safe inset | Move type/codes inside trim minus `safe_area_mm` |
| `REQUIRED_COPY_MISSING` | String not in SVG/PDF text | Match the exact characters; outlined type is not searchable |
| `CODE_VALUE_MISMATCH` | QR/barcode decodes to something else | Check the expected value; UPC-A may decode as EAN-13 |
| `PDF_INVALID` / `SVG_INVALID` / `PNG_INVALID` | Malformed file or unreadable image data | Re-export a valid file; LABELOS fails closed instead of crashing |
| `SVG_UNSAFE_XML` | SVG declares a DOCTYPE or entity | Re-export without a DTD so required copy is literal text |
| `verify-package` checksum mismatch | File changed after packaging | Re-run `package` to a new directory; never edit a package |
| Callas skipped | Not licensed | Expected. Do not treat as commercial preflight PASS |
| API 401 | Future API token missing | Operators should use the CLI, not the API |
