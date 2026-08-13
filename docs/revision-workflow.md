# Revision workflow

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

Approval captures approver, timestamp, comments, and the **exact artwork SHA-256** being approved.
Technical validation is not legal/regulatory approval.
