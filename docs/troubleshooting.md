# Troubleshooting

| Symptom | Likely cause | Action |
| --- | --- | --- |
| API 401 | Missing/wrong Bearer token | Confirm `LABELOS_API_TOKEN` matches n8n credential |
| `PATH_TRAVERSAL` | Destination outside storage | Keep paths under `LABELOS_STORAGE_PATH` |
| `REJECTED_VALIDATION` | Artwork/spec mismatch | Inspect `result.failed` and `checks` |
| `DUPLICATE_SKIPPED` | Same identity already processed | Use `RERUN` or `NEW_REVISION` |
| `PACKAGE_VERIFICATION_FAILED` | Tamper or incomplete package | Re-package; never release |
| `ILLUSTRATOR_UNAVAILABLE` | No COM / not Windows / Illustrator closed | Use workstation + open Illustrator or `dry_run` |
| `PRODUCT_SCHEMA_INVALID` | Bad product JSON | Fix schema before generation |
| Callas skipped | Not licensed | Expected until adapter configured |

Structured logs include `job_id`, `sku`, `revision`, `operation`, `status`, `duration_ms`, `error_code`.
