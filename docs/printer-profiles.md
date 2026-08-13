# Printer profiles

Printer profiles eventually encode page size, bleed, safe area, color space, ICC, PDF standard,
minimum type/line weights, black construction, overprint, barcode rules, ink limits, and dielines.

## Hard rule

**Do not invent printer-specific limits.** Populate profiles only from approved printer specifications.

The schema lives at [`profiles/printer-profile.schema.example.json`](../profiles/printer-profile.schema.example.json).

`approved: false` profiles are never enforced.

Profiles are loaded from `LABELOS_PRINTER_PROFILES_PATH`; `labelos doctor` reports the
component as `missing` when the variable is unset or the directory is empty.

## Status

**EXTERNAL BLOCKER — NOT CLAIMED COMPLETE.** No approved converter/printer specification has
been supplied, so no production profile values exist in this repository. LABELOS must not
release a SKU that has no approved profile.
