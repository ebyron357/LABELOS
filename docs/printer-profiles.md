# Printer profiles

Printer profiles eventually encode page size, bleed, safe area, color space, ICC, PDF standard,
minimum type/line weights, black construction, overprint, barcode rules, ink limits, and dielines.

## Hard rule

**Do not invent printer-specific limits.** Populate profiles only from approved printer specifications.

The schema lives at [`profiles/printer-profile.schema.example.json`](../profiles/printer-profile.schema.example.json).

`approved: false` profiles are never enforced.

## Status

**PLACEHOLDER** until an approved printer specification document is supplied.
