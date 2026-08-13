# Backup and recovery

## What to back up

Under `LABELOS_STORAGE_PATH`:

```text
source/ templates/ generated/ validation/ approved/ releases/ archive/ jobs/
```

Priority: `releases/`, `jobs/`, `approved/`, `templates/`.

## Recovery checks

1. Restore storage volume
2. `GET /health`
3. `GET /doctor`
4. `POST /verify-package` for each critical release directory
5. Confirm job index `jobs/index.json` loads

## Provider portability

`LocalStorage` is the default backend. The storage interface is intentionally narrow so S3-compatible,
Drive, NAS, or DAM adapters can be added without changing validation logic.
