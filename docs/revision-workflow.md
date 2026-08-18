# Revision workflow

**Status: FUTURE** for job-lifecycle orchestration. The operator release path today is
validate → package → verify-package.


## Lifecycle

```text
DRAFT
→ DATA_READY
→ ARTWORK_GENERATED
→ ARTWORK_REVIEW
→ TECHNICALLY_VALIDATED
→ AWAITING_APPROVAL
→ APPROVED_FOR_PRODUCTION
→ RELEASED
→ ARCHIVED
```

Correction path:

```text
ARTWORK_REVIEW / REJECTED_VALIDATION / REJECTED_BY_APPROVER
→ CORRECTION_REQUIRED
→ ARTWORK_GENERATED / DATA_READY
```

## Revisions

Example:

```text
ALT-SYR-MANGO-001
  1.0
  1.1
  2.0
```

Each revision stores template checksum, product-data checksum, artwork checksum, config checksum,
validation report, approval, package, and timestamps.

## Immutability

- Approved releases are never overwritten
- Package destinations refuse to replace existing directories
- Duplicate identity submissions return `DUPLICATE_SKIPPED` unless `RERUN` or `NEW_REVISION`

## Approval binding

`approve` is available only after `verify-package` has succeeded and transitioned the job
to `AWAITING_APPROVAL`. Approval captures approver, timestamp, comments, and the
**exact artwork SHA-256 from the generated package manifest**—not the checksum from the
original input path. `release` requires that the saved verification checksum still matches
the current package manifest and that the approval checksum still matches packaged artwork.

Technical validation is not legal/regulatory approval.
