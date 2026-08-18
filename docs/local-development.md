# Local development

## Prerequisites

- Python 3.10+

## Setup

```bash
python -m pip install -e ".[test,dev]"
labelos doctor --json
```

## Operator CLI

```bash
labelos validate examples/label.json --json
labelos package examples/label.json storage/demo-release
labelos verify-package storage/demo-release
```

## Tests

```bash
python -m pytest
python -m ruff check .
python -m compileall -q labelos tests
python -m build
```

## Optional automation (future)

The HTTP API and Illustrator bridge are not required for production validation.
See [docs/api.md](api.md) and [docs/illustrator-setup.md](illustrator-setup.md) only if
you are extending those future paths.
