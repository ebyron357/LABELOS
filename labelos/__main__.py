"""Module entry point for operators without the console script on PATH."""

if __name__ == "__main__":
    from .cli import main

    raise SystemExit(main())
