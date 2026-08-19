# Deployment

**Status: OPTIONAL.** Operators use the local CLI today. This document describes an
HTTP API deploy path that is not required for production artwork validation.


## Required environment

| Variable | Required | Purpose |
| --- | --- | --- |
| `LABELOS_API_TOKEN` | yes | Bearer token for API auth |
| `LABELOS_STORAGE_PATH` | yes in prod | Durable storage root |
| `LABELOS_API_HOST` | no | Default `0.0.0.0` |
| `PORT` | set by Render | Listen port (preferred over `LABELOS_API_PORT`) |
| `LABELOS_API_PORT` | no | Fallback listen port when `PORT` is unset (local/Docker default `8080`) |
| `LABELOS_LOG_LEVEL` | no | Default `INFO` |
| `LABELOS_API_BASE_URL` | n8n only | Public HTTPS base URL for n8n HTTP nodes |

## Container (optional alternative to Render native Python)

```bash
docker build -t labelos-api:0.2.0 .
docker run --rm -p 8080:8080 \
  -e LABELOS_API_TOKEN=<long-random-secret> \
  -e LABELOS_STORAGE_PATH=/data/storage \
  -v labelos-data:/data/storage \
  labelos-api:0.2.0
```

Or: `docker compose up --build`

## Health

- `GET /health` — unauthenticated liveness (Render `healthCheckPath`)
- `GET /doctor` — authenticated dependency report

## Render Blueprint (recommended for n8n reachability)

Blueprint file: [`render.yaml`](../render.yaml)

### Exact procedure

1. Open [https://dashboard.render.com](https://dashboard.render.com) and sign in.
2. Ensure a workspace that can create a **Starter** (or higher) web service with a **persistent disk**.
3. Click **New → Blueprint**.
4. Connect GitHub repo `ebyron357/LABELOS` if not already connected.
5. Select branch **`main`**, which contains the canonical validated release engine.
6. Confirm Render detects `render.yaml` and the service name **`labelos-api`**.
7. When prompted for `LABELOS_API_TOKEN`, paste a strong secret (generation below). Do not leave it blank.
8. Apply / create the Blueprint and wait until the deploy status is **Live**.
9. Open the service page and copy the public URL shown at the top (HTTPS).

### Public URL → `LABELOS_API_BASE_URL`

Render assigns the public hostname at provision time.

- Service name in Blueprint: `labelos-api`
- Expected form: `https://labelos-api.onrender.com`
- If that name is taken, Render may assign a suffix, e.g. `https://labelos-api-XXXX.onrender.com`

**Use the exact URL from the Render service page** (no trailing slash) as:

```text
LABELOS_API_BASE_URL=https://<labelos-api-host>.onrender.com
```

Do not invent the hostname. Confirm it in the Dashboard after the first successful deploy.

### Generate a strong `LABELOS_API_TOKEN`

Generate a 32+ byte URL-safe secret locally, then set the **same** value in Render and in n8n:

```bash
# PowerShell
[Convert]::ToBase64String((1..48 | ForEach-Object { Get-Random -Maximum 256 }) -as [byte[]]).TrimEnd('=')

# or Python
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Store it only in:

1. Render env var `LABELOS_API_TOKEN`
2. n8n credential **LABELOS API Token** (Bearer / Header Auth)

Never commit the token. Never put it in the repo.

### Post-deploy health checks

Replace `BASE` with the Render public URL (no trailing slash):

```bash
# Unauthenticated liveness — expect success=true
curl -sS "$BASE/health"

# Missing auth — expect HTTP 401
curl -sS -o /dev/null -w "%{http_code}\n" "$BASE/doctor"

# Authenticated doctor — expect success=true and tools payload
curl -sS -H "Authorization: Bearer $LABELOS_API_TOKEN" "$BASE/doctor"
```

PowerShell equivalents:

```powershell
Invoke-RestMethod "$env:LABELOS_API_BASE_URL/health"
Invoke-RestMethod -Headers @{ Authorization = "Bearer $env:LABELOS_API_TOKEN" } "$env:LABELOS_API_BASE_URL/doctor"
```

Only after both `/health` and authenticated `/doctor` succeed is the API **DEPLOYED AND VERIFIED**.

### n8n Cloud settings (after URL is live)

In n8n Cloud (`bwa357.app.n8n.cloud`), workflow **LABELOS Label Validation & Release** (`6CwUVmFDLQbzdNBd`):

| Setting | Exact value |
| --- | --- |
| Variable / env `LABELOS_API_BASE_URL` | Render public URL, **no trailing slash** (example form `https://labelos-api.onrender.com`) |
| Credential name | `LABELOS API Token` |
| Credential type | Header Auth **or** Bearer Auth |
| Header name (if Header Auth) | `Authorization` |
| Header/Bearer value | `Bearer <same LABELOS_API_TOKEN as Render>` **or** token only if the credential type prepends `Bearer ` |
| Doctor URL | `{{ $env.LABELOS_API_BASE_URL }}/doctor` (GET) |
| Validate URL | `{{ $env.LABELOS_API_BASE_URL }}/validate` (POST JSON) |
| Package URL | `{{ $env.LABELOS_API_BASE_URL }}/package` (POST JSON) |
| Verify URL | `{{ $env.LABELOS_API_BASE_URL }}/verify-package` (POST JSON) |

Import reference scaffold: [`n8n/labelos-label-validation-release.n8n.json`](../n8n/labelos-label-validation-release.n8n.json).

Replace every mocked LABELOS Set/Code response with the HTTP Request nodes above. Do not hardcode the hostname inside nodes.

## Notes

- Persistent disk disables zero-downtime deploys and horizontal scaling on that service (Render constraint). Acceptable for LABELOS release storage.
- The Illustrator bridge is **not** part of this Render service; it stays on a workstation.
- Docker image path remains valid for non-Render hosts; bind `PORT` or `LABELOS_API_PORT` accordingly.
