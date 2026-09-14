"""Run LABELOS without requiring the console-script directory on PATH."""

from labelos.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
