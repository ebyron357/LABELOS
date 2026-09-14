# Local development

## Prerequisites

- Python 3.10+

## Setup

```bash
python3 -m pip install -e ".[test,dev]"
python3 -m labelos doctor --json
```

## Operator CLI

```bash
python3 -m labelos validate examples/label.json --json
python3 -m labelos package examples/label.json storage/demo-release
python3 -m labelos verify-package storage/demo-release
```

## Tests

```bash
python3 -m pytest
python3 -m ruff check .
python3 -m compileall -q labelos tests
python3 -m build
```

## Optional automation (future)

The HTTP API and Illustrator bridge are not required for production validation.
See [docs/api.md](api.md) and [docs/illustrator-setup.md](illustrator-setup.md) only if
you are extending those future paths.
