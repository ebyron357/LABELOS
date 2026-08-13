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
| `NOT_CONFIGURED` preflight | `LABELOS_PDFTOOLBOX_PATH`/`_PROFILE` unset or CLI absent | Configure the licensed CLI ([docs/pdftoolbox-setup.md](pdftoolbox-setup.md)) |
| `TOOL_ERROR` preflight | CLI crashed, timed out, or wrote no parsable report | Inspect `preflight_result.details.stderr`; verify flags for the installed build |
| `PREPRESS_FAILED` | pdfToolbox reported error hits | Fix artwork; a `FAIL` never releases |
| `RELEASE_VERIFICATION_REQUIRED` | Package was never verified, or was re-packaged after verification | Run `/verify-package` for the job again |
| `RELEASE_PACKAGE_TAMPERED` | Package contents changed after verification | Re-package from source; never release a tampered package |
| `APPROVAL_CHECKSUM_MISMATCH` | Approval checksum ≠ packaged artwork checksum | Approve against `package_artwork_checksum` |
| `ILLEGAL_TRANSITION` | Lifecycle step attempted out of order | Follow the documented lifecycle |

Structured logs include `job_id`, `sku`, `revision`, `operation`, `status`, `duration_ms`, `error_code`.
