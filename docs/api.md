# LABELOS HTTP API

**Status: FUTURE / optional.** Production operators should use the CLI in the
[README](../README.md). This API is an automation facade over the same validator;
it is not required to validate or release artwork today.


Base URL: `$LABELOS_API_BASE_URL`

Auth: `Authorization: Bearer $LABELOS_API_TOKEN` on all routes except `/health`.

## Common envelope

```json
{
  "success": true,
  "job_id": "JOB-...",
  "status": "PASS",
  "exit_code": 0,
  "stdout": "",
  "stderr": "",
  "timestamp": "2026-08-11T00:00:00+00:00",
  "result": {}
}
```

## Endpoints

### `GET /health`

Unauthenticated liveness.

### `GET /doctor`

Reports PyMuPDF, ZXing-C++, Callas adapter status.

### `POST /validate`

Body:

```json
{ "config": { "artwork": "...", "width_mm": 100, "height_mm": 50 }, "job_id": null }
```

Result includes structured checks:

```json
{
  "overall": "PASS",
  "failed": [],
  "checks": [{ "code": "FORMAT_SVG", "status": "PASS", "description": "..." }]
}
```

### `POST /package`

Body: `{ "config": {...}, "destination": "adhoc/name" }` or `{ "job_id": "JOB-..." }`.

Destinations are always resolved under `LABELOS_STORAGE_PATH`.

### `POST /verify-package`

Body: `{ "destination": "..." }` or `{ "job_id": "JOB-..." }`.

### `POST /jobs`

Creates an auditable job with idempotency identity.

Modes: `NORMAL` (duplicate → `DUPLICATE_SKIPPED`), `RERUN`, `NEW_REVISION`.

### `GET /jobs/{job_id}`

### `GET /jobs/{job_id}/report`

### `GET /jobs/{job_id}/package`

### `POST /jobs/{job_id}/approve`

Requires `approver` and a successful job-scoped `POST /verify-package`. The optional
artwork checksum must exactly match the artwork checksum in the generated package manifest;
when omitted, the packaged value is bound automatically.

### `POST /jobs/{job_id}/release`

Requires `APPROVED_FOR_PRODUCTION`, a verification checksum matching the current package
manifest, and approval bound to the packaged artwork checksum.
