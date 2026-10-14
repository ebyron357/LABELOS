"""Support ``python -m labelos`` for operators without a console-script shim."""

from .cli import main

raise SystemExit(main())
