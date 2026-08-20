# LABELOS Architecture

## Canonical product (today)

LABELOS is a local **validation and release engine**. The supported operator path is the
CLI: `validate` → `package` → `verify-package`, plus `doctor` for environment checks.

```text
Label spec JSON + artwork (SVG / PNG / PDF)
  → labelos validate
  → structured report (pass or fail-closed errors)
  → labelos package   (refuses failed reports)
  → labelos verify-package
  → release directory (artwork, safe linked SVG rasters, report, spec + SHA-256 manifest)
```

Callas pdfToolbox is an optional commercial adapter. Until it is licensed and configured,
validation records `preflight.status = SKIPPED_NOT_CONFIGURED` and never fakes a pass.

## Optional / future layers (present in tree, not required)

| Layer | Status |
| --- | --- |
| HTTP API (`labelos-api`) | FUTURE / optional automation |
| Illustrator bridge | FUTURE; live COM needs a Windows workstation |
| n8n workflow scaffold | FUTURE; cloud cutover not done |
| Printer ICC / Callas profiles | EXTERNAL DEPENDENCY; not configured |

Do not treat those layers as the production operator path.

## Fail-closed rules

A release package is created only when validation has no error-severity issues.
Verification fails if the manifest is malformed, files are missing or not regular files,
paths escape the package directory, checksums or byte counts disagree, or the stored
report does not record a pass.

For SVG artwork, local linked raster assets are accepted only when they are relative,
non-symlink files within the artwork directory. They are decoded for effective-DPI
validation and copied into schema-2 release packages with their own checksums. URLs,
fragments, traversal paths, missing files, and symlinks fail validation.
