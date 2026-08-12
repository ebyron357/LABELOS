# Local development

## Prerequisites

- Python 3.10+
- Optional: Docker
- Optional (bridge live mode): Windows + Adobe Illustrator + `pip install -e ".[bridge]"`

## Setup

```bash
python -m pip install -e ".[test,dev]"
copy .env.example .env   # Windows
# set LABELOS_API_TOKEN to a long random secret
```

## CLI (unchanged)

```bash
labelos validate examples/label.json --json
labelos package examples/label.json storage/releases/demo/1.0/manual
labelos verify-package storage/releases/demo/1.0/manual
labelos doctor --json
```

## API

```bash
set LABELOS_API_TOKEN=dev-secret
set LABELOS_STORAGE_PATH=%CD%\storage
labelos-api
```

```bash
curl -s http://127.0.0.1:8080/health
curl -s -H "Authorization: Bearer dev-secret" http://127.0.0.1:8080/doctor
```

## Tests

```bash
python -m pytest
python -m ruff check .
```

## Illustrator bridge (workstation)

```bash
set LABELOS_BRIDGE_TOKEN=%LABELOS_API_TOKEN%
set LABELOS_TEMPLATES_PATH=%CD%\templates
labelos-bridge
```

Use `"dry_run": true` on `/generate` in CI / machines without Illustrator.
