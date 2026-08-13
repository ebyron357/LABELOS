# LABELOS production status

Canonical production-readiness record. Supersedes all earlier status notes.

## Verdict

**NO-GO — NOT YET FINALIZED.**

All repository-controlled software gates are PASS. The real end-to-end production run cannot
be executed here: licensed callas pdfToolbox, a licensed Adobe Illustrator Windows workstation
with an approved `.ai` master, approved printer specifications, approved product/label copy, a
deployed API, and n8n credentials are unavailable to the build environment.

## Subsystem matrix

| Subsystem | Status |
| --- | --- |
| LABELOS Core | PASS |
| API | PASS (implementation + tests); live deployment EXTERNAL BLOCKER |
| Authentication | PASS |
| Job State Machine | PASS |
| Illustrator Bridge | PASS (bridge logic, validation, dry-run) |
| Live Illustrator | EXTERNAL BLOCKER — NOT CLAIMED COMPLETE |
| Product Schema | PASS |
| Real Production Data | EXTERNAL BLOCKER — NOT CLAIMED COMPLETE |
| Printer Profiles | Schema PASS; approved values EXTERNAL BLOCKER — NOT CLAIMED COMPLETE |
| pdfToolbox CLI | EXTERNAL BLOCKER — NOT CLAIMED COMPLETE |
| pdfToolbox Adapter | PASS |
| PDF Preflight | EXTERNAL BLOCKER — NOT CLAIMED COMPLETE |
| Barcode Validation | PASS |
| QR Validation | PASS |
| Packaging | PASS |
| Manifest Integrity | PASS |
| Approval Integrity | PASS |
| Release Gate | PASS |
| n8n Automation | Workflow definition PASS; live cutover EXTERNAL BLOCKER — NOT CLAIMED COMPLETE |
| Audit Trail | PASS |
| Documentation | PASS |
| CI | PASS locally; GitHub Actions run on the merge SHA EXTERNAL BLOCKER |
| Real E2E Production Run | EXTERNAL BLOCKER — NOT CLAIMED COMPLETE |

## Implemented and verified in this repository

- Validation engine: dimensions, bleed, safe area, DPI, required copy, barcode/QR decoding
  (SVG/PNG/PDF, rasterized at 300 DPI), fail-closed on decoder unavailability.
- Authenticated HTTP API: `/health`, `/ready`, `/doctor`, `/validate`, `/package`,
  `/verify-package`, job/approval/release endpoints, structured error envelope.
- Durable job store with identity/idempotency, audit history, timestamps, actor, checksums.
- Lifecycle enforcement with rejected illegal transitions.
- Release integrity:
  - packaging requires a passing validation report;
  - approval requires a verified package and binds to the packaged artwork checksum;
  - re-packaging clears prior verification;
  - release re-verifies the package atomically and rejects tampering.
- Real callas pdfToolbox CLI adapter (`labelos/preflight.py`): environment-configured
  executable/profile, machine-readable JSON report capture, corrected PDF written to a separate
  file, and `PASS`/`WARNING`/`FAIL`/`TOOL_ERROR`/`NOT_CONFIGURED` normalization.
- `labelos doctor` (`labelos/doctor.py`) reporting every production dependency as exactly one of
  `ready`, `configured`, `missing`, `unavailable`, `unhealthy` — never `ready` for an unverified
  dependency.
- Illustrator bridge with export-format validation (`pdf`, `ai`, `png` only) and zero-output
  failure.
- Deployment configuration: `Dockerfile`, `docker-compose.yml`, `render.yaml`, `.env.example`.

## Quality gates (this branch)

```text
python -m pytest -q                                     # 71 passed
python -m ruff check labelos illustrator_bridge tests   # All checks passed
python -m build                                         # labelos-0.2.0 sdist + wheel
```

## External blockers

Each item below is **EXTERNAL BLOCKER — NOT CLAIMED COMPLETE**.

| Dependency | Missing item | Operator action | Verify afterwards |
| --- | --- | --- | --- |
| callas pdfToolbox | Licensed CLI + approved `.kfpx` profile | Install; set `LABELOS_PDFTOOLBOX_PATH`, `LABELOS_PDFTOOLBOX_PROFILE` | `labelos doctor --json` → `pdftoolbox.state == "ready"`; run a job with `required=True` |
| Adobe Illustrator | Licensed Illustrator on a Windows workstation + approved `.ai` master | Install; set `LABELOS_TEMPLATES_PATH`, `LABELOS_ILLUSTRATOR_TEMPLATE`; start the bridge | `POST /generate` on the bridge with `dry_run=false` |
| Printer profiles | Approved converter/printer specification document | Author profiles under `LABELOS_PRINTER_PROFILES_PATH` from the supplied spec | `labelos doctor`; release attempt without a profile must fail |
| Approved product data | Approved copy, ingredients, warnings, UPC/GTIN, QR destination, dieline | Supply approved records under `LABELOS_PRODUCT_DATA_PATH` | `POST /jobs` with the real record |
| Deployment | Hosting account + production secret | Deploy `render.yaml`; set `LABELOS_API_TOKEN`, `LABELOS_STORAGE_PATH` (persistent disk), `LABELOS_API_BASE_URL` | `GET /health`, `GET /ready`, authenticated `GET /doctor`; restart and confirm storage survives |
| n8n cutover | n8n credentials for workflow `6CwUVmFDLQbzdNBd` | Replace mocked LABELOS nodes with HTTP nodes against `LABELOS_API_BASE_URL` | Execute the workflow; confirm job IDs and audit records |
| GitHub merge/CI | Write access to merge into `main` and read the resulting Actions run | Merge the release PR; inspect the run | Green CI on the merged `main` SHA |
| Real E2E run | All of the above | Execute one approved SKU end to end | Released package with manifest, reports, approval record, audit log |

## Next required action

Install and configure the licensed callas pdfToolbox CLI, then run `labelos doctor --json` and
record the output. Everything downstream (real preflight, real E2E, GO/NO-GO) depends on it.
