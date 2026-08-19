"""Enable ``python -m labelos`` for operator environments without script PATH setup."""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
