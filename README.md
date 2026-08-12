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
GET  /health
GET  /doctor
POST /validate
POST /package
POST /verify-package
POST /jobs
GET  /jobs/{job_id}
```

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
| Security | [docs/security.md](docs/security.md) |
| Backup | [docs/backup-recovery.md](docs/backup-recovery.md) |
| Acceptance | [docs/acceptance-testing.md](docs/acceptance-testing.md) |
| Troubleshooting | [docs/troubleshooting.md](docs/troubleshooting.md) |

## Current scope

The core validator remains fail-closed. Commercial Callas preflight, approved regulatory copy,
brand `.ai` templates, and printer ICC targets must be supplied by owners before a SKU can be
certified for print. See [PROJECT_STATUS.md](PROJECT_STATUS.md).
