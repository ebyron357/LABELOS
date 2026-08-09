"""Operator-facing command line interface."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .models import LabelSpec
from .package import create_package, verify_package
from .validate import validate


def _load_spec(path: Path) -> LabelSpec:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ValueError(f"Configuration file does not exist: {path}") from None
    except json.JSONDecodeError as error:
        raise ValueError(f"Configuration is not valid JSON: {error}") from None
    if not isinstance(data, dict):
        raise ValueError("Configuration root must be a JSON object")
    return LabelSpec.from_dict(data, path.parent)


def _print_report(report: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(report, indent=2, sort_keys=True))
        return
    print(f"{'PASS' if report['passed'] else 'FAIL'} {report['source']}")
    for issue in report["issues"]:
        print(f"{issue['severity'].upper():7} {issue['code']}: {issue['message']}")


def _doctor() -> dict:
    tools = {}
    for name, module in (("PyMuPDF", "fitz"), ("ZXing-C++", "zxingcpp"), ("Callas pdfToolbox", None)):
        if module is None:
            tools[name] = {"available": False, "status": "optional commercial adapter not configured"}
            continue
        try:
            __import__(module)
            tools[name] = {"available": True, "status": "available"}
        except ImportError:
            tools[name] = {"available": False, "status": f"install Python module {module}"}
    return {"passed": True, "tools": tools}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="labelos", description="Validate and package production labels")
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate_parser = subparsers.add_parser("validate", help="Validate a label configuration")
    validate_parser.add_argument("config", type=Path)
    validate_parser.add_argument("--json", action="store_true", help="Print machine-readable report")
    package_parser = subparsers.add_parser("package", help="Validate then create a release package")
    package_parser.add_argument("config", type=Path)
    package_parser.add_argument("destination", type=Path)
    package_parser.add_argument("--json", action="store_true", help="Print machine-readable output")
    verify_parser = subparsers.add_parser("verify-package", help="Verify release-package checksums")
    verify_parser.add_argument("destination", type=Path)
    verify_parser.add_argument("--json", action="store_true", help="Print machine-readable output")
    doctor_parser = subparsers.add_parser("doctor", help="Report available optional validators")
    doctor_parser.add_argument("--json", action="store_true", help="Print machine-readable output")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "doctor":
            result = _doctor()
            print(json.dumps(result, indent=2, sort_keys=True) if args.json else json.dumps(result["tools"], indent=2))
            return 0
        if args.command == "verify-package":
            failures = verify_package(args.destination)
            result = {"passed": not failures, "issues": failures}
            print(json.dumps(result, indent=2, sort_keys=True) if args.json else "\n".join(failures or ["PASS"]))
            return 0 if not failures else 1
        spec = _load_spec(args.config)
        report = validate(spec)
        if args.command == "package" and report.passed:
            manifest = create_package(spec, report, args.destination)
            report.metadata["manifest"] = str(manifest)
        _print_report(report.to_dict(), args.json)
        return 0 if report.passed else 1
    except (ValueError, FileExistsError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
