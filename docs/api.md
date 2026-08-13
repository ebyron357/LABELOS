# LABELOS HTTP API

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

Reports every production dependency (core, Python, storage, API, Illustrator bridge, Adobe
Illustrator, pdfToolbox, n8n, printer profiles, product data, production config) with one of
`ready`, `configured`, `missing`, `unavailable`, `unhealthy`. `GET /ready` is the unauthenticated
readiness probe and returns 503 when storage or the API token is not usable.

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

Requires `approver` and artwork checksum binding.

### `POST /jobs/{job_id}/release`

Requires `APPROVED_FOR_PRODUCTION` + verified package.
