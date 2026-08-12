# Deployment

## Container

```bash
docker build -t labelos-api:0.2.0 .
docker run --rm -p 8080:8080 \
  -e LABELOS_API_TOKEN=<long-random-secret> \
  -e LABELOS_STORAGE_PATH=/data/storage \
  -v labelos-data:/data/storage \
  labelos-api:0.2.0
```

Or:

```bash
docker compose up --build
```

## Required environment

| Variable | Required | Purpose |
| --- | --- | --- |
| `LABELOS_API_TOKEN` | yes | Bearer token for API auth |
| `LABELOS_STORAGE_PATH` | yes in prod | Durable storage root |
| `LABELOS_API_HOST` | no | Default `0.0.0.0` |
| `LABELOS_API_PORT` | no | Default `8080` |
| `LABELOS_LOG_LEVEL` | no | Default `INFO` |
| `LABELOS_API_BASE_URL` | n8n | Public base URL consumed by n8n |

## Health

- `GET /health` — unauthenticated liveness
- Docker `HEALTHCHECK` curls `/health`
- `GET /doctor` — authenticated dependency report

## Render Blueprint

[`render.yaml`](../render.yaml) defines a Python web service with a persistent disk for
`LABELOS_STORAGE_PATH`.

1. Push branch `feat/production-label-automation`
2. In Render: **New → Blueprint** → select `ebyron357/LABELOS`
3. Set secret `LABELOS_API_TOKEN` in the dashboard
4. After deploy, set n8n `LABELOS_API_BASE_URL` to `https://<service>.onrender.com`

Verify:

```bash
curl -s https://<service>.onrender.com/health
curl -s -H "Authorization: Bearer $LABELOS_API_TOKEN" https://<service>.onrender.com/doctor
```
