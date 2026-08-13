# LABELOS

LABELOS validates packaging-label artwork before production release, creates checksummed
immutable packages, and exposes an authenticated HTTP API for n8n orchestration.

Illustrator automation runs on a controlled workstation bridge — not as an unsupported
headless cloud process.

## Quick start

```bash
python -m pip install -e ".[test,dev]"
labelos validate examples/label.json --json
labelos package examples/label.json storage/demo-release
labelos verify-package storage/demo-release
labelos doctor --json
```

## HTTP API

```bash
set LABELOS_API_TOKEN=dev-secret
set LABELOS_STORAGE_PATH=%CD%\storage
labelos-api
```

```text
GET  /health                       liveness
GET  /ready                        readiness (storage writable + API token configured)
GET  /doctor                       production dependency states
POST /validate
POST /package
POST /verify-package
POST /jobs
GET  /jobs/{job_id}
GET  /jobs/{job_id}/report
GET  /jobs/{job_id}/package
POST /jobs/{job_id}/approve
POST /jobs/{job_id}/release
```

Every endpoint except `/health` and `/ready` requires `Authorization: ******

See [docs/api.md](docs/api.md).

## Documentation

| Topic | Doc |
| --- | --- |
| Architecture | [docs/architecture.md](docs/architecture.md) |
| Local development | [docs/local-development.md](docs/local-development.md) |
| Deployment | [docs/deployment.md](docs/deployment.md) |
| n8n | [docs/n8n-configuration.md](docs/n8n-configuration.md) |
| Illustrator setup | [docs/illustrator-setup.md](docs/illustrator-setup.md) |
| Template standard | [docs/illustrator-template-standard.md](docs/illustrator-template-standard.md) |
| Product schema | [docs/product-data-schema.md](docs/product-data-schema.md) |
| Revisions | [docs/revision-workflow.md](docs/revision-workflow.md) |
| Printer profiles | [docs/printer-profiles.md](docs/printer-profiles.md) |
| callas pdfToolbox | [docs/pdftoolbox-setup.md](docs/pdftoolbox-setup.md) |
| Security | [docs/security.md](docs/security.md) |
| Backup | [docs/backup-recovery.md](docs/backup-recovery.md) |
| Acceptance | [docs/acceptance-testing.md](docs/acceptance-testing.md) |
| Troubleshooting | [docs/troubleshooting.md](docs/troubleshooting.md) |

## Release lifecycle (fail-closed)

```text
DRAFT → DATA_READY → ARTWORK_GENERATED → TECHNICALLY_VALIDATED
      → (package) → package verification → AWAITING_APPROVAL
      → APPROVED_FOR_PRODUCTION → RELEASED → ARCHIVED
```

Enforced invariants:

- Packaging requires a passing validation report.
- Approval requires a **successfully verified** package and is bound to the SHA-256 checksum of
  the artwork actually written into that package.
- Release re-verifies the package atomically; any change to the package or its manifest after
  verification blocks release (`RELEASE_PACKAGE_TAMPERED`).
- Re-packaging clears any previous verification.
- Illegal lifecycle transitions are rejected (`ILLEGAL_TRANSITION`).
- Required callas pdfToolbox preflight blocks release on `FAIL`, `TOOL_ERROR`, and
  `NOT_CONFIGURED`.

## Environment variables

| Variable | Purpose |
| --- | --- |
| `LABELOS_API_TOKEN` | ****** required by every authenticated endpoint |
| `LABELOS_STORAGE_PATH` | Persistent storage root (jobs, releases, audit) |
| `LABELOS_API_BASE_URL` | Permanent public API base URL used by n8n |
| `LABELOS_API_HOST` / `PORT` / `LABELOS_API_PORT` | Listen address; platform `PORT` wins |
| `LABELOS_LOG_LEVEL` | Structured log level |
| `LABELOS_PDFTOOLBOX_PATH` / `_PROFILE` / `_FIXUP_PROFILE` / `_TIMEOUT` | callas pdfToolbox CLI |
| `LABELOS_BRIDGE_URL` / `LABELOS_BRIDGE_TOKEN` / `LABELOS_TEMPLATES_PATH` | Illustrator bridge |
| `LABELOS_ILLUSTRATOR_TEMPLATE` | Approved `.ai` master on the workstation |
| `LABELOS_PRINTER_PROFILES_PATH` | Approved printer-profile directory |
| `LABELOS_PRODUCT_DATA_PATH` | Approved product-data directory |
| `LABELOS_N8N_WORKFLOW_ID` | Production n8n workflow identifier |

Secrets are never committed; `.env` is git-ignored and `.env.example` contains placeholders only.

## Current scope

The core validator, API, job state machine, packaging, and the pdfToolbox adapter are
implemented and tested. A licensed callas pdfToolbox installation, approved printer
specifications, approved product data/`.ai` masters, a live Illustrator workstation, a deployed
API, and the n8n cutover remain external dependencies. See [PROJECT_STATUS.md](PROJECT_STATUS.md).
