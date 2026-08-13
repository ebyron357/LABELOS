# n8n configuration

## Target workflow

- Name: **LABELOS Label Validation & Release**
- Workflow ID: `6CwUVmFDLQbzdNBd`
- Environment: `bwa357.app.n8n.cloud`

## Credentials / variables

| Name | Type | Value |
| --- | --- | --- |
| `LABELOS_API_BASE_URL` | Variable | Public URL of the deployed LABELOS API |
| `LABELOS API Token` | Bearer auth credential | Same secret as `LABELOS_API_TOKEN` |

Never hardcode the service URL in nodes. Use:

```text
{{ $env.LABELOS_API_BASE_URL }}/validate
```

(or the n8n variable expression your cloud workspace uses).

## Required real calls (replace mocks)

1. `GET {{base}}/doctor`
2. `POST {{base}}/validate` with JSON config / job_id
3. `POST {{base}}/package` after validation PASS
4. `POST {{base}}/verify-package` before approval / release

All authenticated requests must send:

```http
Authorization: Bearer <LABELOS API Token>
```

## Importable workflow scaffold

See [`n8n/labelos-label-validation-release.n8n.json`](../n8n/labelos-label-validation-release.n8n.json).

Import into n8n Cloud, attach the Bearer credential, set `LABELOS_API_BASE_URL`, then deactivate mock/set nodes.

## Registry

The existing Data Table `labelos_release_registry` may continue to store release metadata mirrored from job results (`job_id`, `sku`, `revision`, checksums, `final_status`).

## Status legend for operators

| Node outcome | Meaning |
| --- | --- |
| Real HTTP to LABELOS | **IMPLEMENTED** once API is deployed and credential attached |
| Mock/Set response nodes | **PLACEHOLDER** — remove after Phase 3 cutover |
| Illustrator generate | Calls bridge when available; otherwise **BLOCKED** on workstation setup |
| Callas | **PLACEHOLDER** adapter until licensed |
