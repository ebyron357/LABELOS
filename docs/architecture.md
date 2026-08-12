# LABELOS Architecture

## System roles

| Layer | Responsibility |
| --- | --- |
| **n8n Cloud** (`bwa357.app.n8n.cloud`) | Orchestration, approvals, notifications, routing, registry updates |
| **LABELOS API** | Authenticated validation, packaging, verification, jobs, audit |
| **Illustrator Automation Bridge** | Workstation agent driving Adobe Illustrator via ExtendScript/COM |
| **Durable storage** (`LABELOS_STORAGE_PATH`) | Source, templates, generated, validation, approved, releases, archive |
| **System of record** | Job JSON + identity index under `storage/jobs` (n8n Data Table `labelos_release_registry` may mirror releases) |

## Production workflow

```text
Product data
  → Illustrator template (bridge)
  → Artwork export
  → LABELOS POST /validate
  → Optional Callas preflight (adapter; disabled until licensed)
  → Human approval (checksum-bound)
  → LABELOS POST /package
  → LABELOS POST /verify-package
  → Production release
  → Archive / audit trail
```

## Fail-closed rules

A release is blocked unless product data is valid, artwork generation succeeded (when required),
LABELOS validation passed, package creation succeeded, package verification passed, required
preflight passed when enabled, and human approval is bound to the artwork checksum.

## Illustrator reality

Adobe Illustrator is automated on a **controlled Windows workstation** using COM
(`Illustrator.Application`) + ExtendScript. It is **not** treated as a headless cloud service.
