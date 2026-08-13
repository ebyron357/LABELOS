# Illustrator setup

## Supported automation architecture

**Preferred / implemented:**

```text
n8n → LABELOS Illustrator Bridge (HTTP, Bearer auth)
    → Windows COM: Illustrator.Application
    → ExtendScript: illustrator_bridge/scripts/generate_label.jsx
    → exported PDF/AI/PNG
    → LABELOS API validate/package
```

This matches Adobe’s supported desktop scripting model. LABELOS does **not** claim unsupported headless cloud Illustrator execution.

## Workstation requirements

1. Windows machine with licensed Adobe Illustrator
2. Python 3.10+ with `pip install -e ".[bridge]"` (installs `pywin32`)
3. Templates directory containing approved `.ai` files
4. Environment:
   - `LABELOS_BRIDGE_TOKEN`
   - `LABELOS_TEMPLATES_PATH`
   - `LABELOS_BRIDGE_OUTPUT_PATH`

## Run

```bash
labelos-bridge
```

Default bind: `127.0.0.1:8090` (keep off the public internet; tunnel or private network only).

## Endpoints

- `GET /health`
- `GET /doctor` (auth)
- `POST /generate` (auth)

`dry_run: true` validates product data and writes an SVG stand-in without launching Illustrator (CI-safe).

## What still requires manual Illustrator work

- Creating the first approved template with correct named objects/layers
- Brand artwork, dielines, and production marks
- Visual design QA before human approval
- Any effect/plugin behavior not expressed as named text frames
