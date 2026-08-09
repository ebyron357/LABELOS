"""Operator CLI for validation, diagnostics, and package delivery."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import sys
from pathlib import Path

import pymupdf as fitz
import zxingcpp

from .models import load_spec
from .package import create_package, export_pdf
from .validator import validate_image, validate_pdf


def _write_json(value: dict[str, object]) -> None:
    print(json.dumps(value, indent=2))


def _validate(args: argparse.Namespace, validator: object) -> int:
    spec = load_spec(args.spec)
    result = validator(args.artwork, spec)  # type: ignore[operator]
    _write_json(result.to_dict())
    return 0 if result.valid else 2


def _doctor(_: argparse.Namespace) -> int:
    payload = {
        "healthy": True,
        "python": sys.version.split()[0],
        "tools": {
            "pymupdf": getattr(fitz, "VersionBind", "available"),
            "zxing_cpp": getattr(zxingcpp, "__version__", "available"),
            "labelos": importlib.metadata.version("labelos"),
        },
        "external_prepress": {
            "callas_pdftoolbox": "TOOL UNAVAILABLE/BLOCKED: no adapter configured",
        },
    }
    _write_json(payload)
    return 0


def _package(args: argparse.Namespace) -> int:
    manifest = create_package(args.artwork, load_spec(args.spec), args.destination)
    _write_json(manifest)
    return 0


def _export(args: argparse.Namespace) -> int:
    output = export_pdf(args.artwork, load_spec(args.spec), args.destination)
    _write_json({"exported_pdf": str(output)})
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="labelos", description="Validate and package production label PDFs."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    doctor = commands.add_parser(
        "doctor", help="report available local and optional production tools"
    )
    doctor.set_defaults(handler=_doctor)
    for command, validator, help_text in (
        ("validate-image", validate_image, "validate raster artwork"),
        ("validate-pdf", validate_pdf, "validate a production PDF"),
    ):
        subparser = commands.add_parser(command, help=help_text)
        subparser.add_argument("artwork", type=Path)
        subparser.add_argument("--spec", type=Path, required=True)
        subparser.set_defaults(handler=lambda args, fn=validator: _validate(args, fn))
    package = commands.add_parser(
        "package", help="validate then produce a checksummed delivery package"
    )
    package.add_argument("artwork", type=Path)
    package.add_argument("--spec", type=Path, required=True)
    package.add_argument("--destination", type=Path, required=True)
    package.set_defaults(handler=_package)
    export = commands.add_parser("export", help="export raster artwork to production-size PDF")
    export.add_argument("artwork", type=Path)
    export.add_argument("--spec", type=Path, required=True)
    export.add_argument("--destination", type=Path, required=True)
    export.set_defaults(handler=_export)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.handler(args)
    except (OSError, ValueError) as exc:
        print(f"labelos: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
