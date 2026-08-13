"""callas pdfToolbox CLI integration.

LABELOS drives the licensed callas pdfToolbox command line interface. The executable
location, preflight profile, and optional fixup profile are supplied through environment
variables so that no workstation-specific path is ever committed:

``LABELOS_PDFTOOLBOX_PATH``
    Absolute path of the pdfToolbox CLI executable.
``LABELOS_PDFTOOLBOX_PROFILE``
    Absolute path of the approved ``.kfpx`` preflight profile.
``LABELOS_PDFTOOLBOX_FIXUP_PROFILE``
    Optional absolute path of an approved fixup profile. When configured, a *corrected*
    PDF is written to a separate file; the source PDF is never overwritten.
``LABELOS_PDFTOOLBOX_TIMEOUT``
    Seconds before the CLI invocation is aborted (default 300).

The adapter never fabricates a pass. When pdfToolbox is not installed/configured the
result is ``NOT_CONFIGURED``; when the CLI cannot be executed or its report cannot be
parsed the result is ``TOOL_ERROR``. Both are blocking for callers that require
commercial preflight.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol

PASS = "PASS"
FAIL = "FAIL"
WARNING = "WARNING"
TOOL_ERROR = "TOOL_ERROR"
NOT_CONFIGURED = "NOT_CONFIGURED"

#: Statuses that must never allow a production release to proceed.
BLOCKING_STATUSES = frozenset({FAIL, TOOL_ERROR, NOT_CONFIGURED})

DEFAULT_TIMEOUT_SECONDS = 300


@dataclass
class PreflightResult:
    """Normalized, machine-readable result of a pdfToolbox preflight run."""

    enabled: bool
    status: str
    profile: str | None = None
    message: str = ""
    exit_code: int | None = None
    report_path: str | None = None
    corrected_pdf: str | None = None
    errors: int = 0
    warnings: int = 0
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def blocking(self) -> bool:
        return self.status in BLOCKING_STATUSES

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["blocking"] = self.blocking
        return payload


class PreflightAdapter(Protocol):
    def run(
        self,
        artwork_path: str,
        profile: str | None = None,
        *,
        output_dir: str | Path | None = None,
    ) -> PreflightResult: ...


@dataclass(frozen=True)
class PdfToolboxConfig:
    executable: str | None
    profile: str | None
    fixup_profile: str | None
    timeout: int

    @property
    def configured(self) -> bool:
        return bool(self.executable and self.profile)


def load_config(env: dict[str, str] | None = None) -> PdfToolboxConfig:
    source: Any = env if env is not None else os.environ
    raw_timeout = str(source.get("LABELOS_PDFTOOLBOX_TIMEOUT", "")).strip()
    try:
        timeout = int(raw_timeout) if raw_timeout else DEFAULT_TIMEOUT_SECONDS
    except ValueError:
        timeout = DEFAULT_TIMEOUT_SECONDS
    if timeout <= 0:
        timeout = DEFAULT_TIMEOUT_SECONDS

    def _value(name: str) -> str | None:
        value = str(source.get(name, "")).strip()
        return value or None

    return PdfToolboxConfig(
        executable=_value("LABELOS_PDFTOOLBOX_PATH"),
        profile=_value("LABELOS_PDFTOOLBOX_PROFILE"),
        fixup_profile=_value("LABELOS_PDFTOOLBOX_FIXUP_PROFILE"),
        timeout=timeout,
    )


def resolve_executable(executable: str | None) -> str | None:
    """Return an executable path if it exists on disk or on PATH, else ``None``."""
    if not executable:
        return None
    candidate = Path(executable).expanduser()
    if candidate.is_file() and os.access(candidate, os.X_OK):
        return str(candidate)
    return shutil.which(executable)


class PdfToolboxAdapter:
    """Real callas pdfToolbox CLI adapter.

    ``runner`` exists so the command-execution boundary can be exercised
    deterministically in CI. It is never used to synthesize preflight verdicts for a
    licensed installation.
    """

    def __init__(
        self,
        config: PdfToolboxConfig | None = None,
        runner: Any | None = None,
    ) -> None:
        self.config = config or load_config()
        self._runner = runner or subprocess.run

    def _execute(self, command: list[str]) -> subprocess.CompletedProcess:
        return self._runner(
            command,
            capture_output=True,
            text=True,
            timeout=self.config.timeout,
            check=False,
        )

    def version(self) -> PreflightResult:
        """Report the installed CLI version, for ``labelos doctor``."""
        executable = resolve_executable(self.config.executable)
        if not executable:
            return PreflightResult(
                enabled=False,
                status=NOT_CONFIGURED,
                message=(
                    "callas pdfToolbox is not configured. Set LABELOS_PDFTOOLBOX_PATH to "
                    "the licensed CLI executable."
                ),
            )
        try:
            completed = self._execute([executable, "--version"])
        except (OSError, subprocess.SubprocessError) as error:
            return PreflightResult(
                enabled=True,
                status=TOOL_ERROR,
                message=f"Could not execute pdfToolbox CLI: {error}",
                details={"executable": executable},
            )
        output = (completed.stdout or completed.stderr or "").strip()
        if completed.returncode != 0:
            return PreflightResult(
                enabled=True,
                status=TOOL_ERROR,
                exit_code=completed.returncode,
                message="pdfToolbox --version returned a non-zero exit code",
                details={"executable": executable, "output": output},
            )
        return PreflightResult(
            enabled=True,
            status=PASS,
            exit_code=0,
            message=output.splitlines()[0] if output else "pdfToolbox CLI responded",
            details={"executable": executable, "output": output},
        )

    def run(
        self,
        artwork_path: str,
        profile: str | None = None,
        *,
        output_dir: str | Path | None = None,
    ) -> PreflightResult:
        profile = profile or self.config.profile
        executable = resolve_executable(self.config.executable)
        if not executable or not profile:
            return PreflightResult(
                enabled=False,
                status=NOT_CONFIGURED,
                profile=profile,
                message=(
                    "callas pdfToolbox is not configured. Set LABELOS_PDFTOOLBOX_PATH and "
                    "LABELOS_PDFTOOLBOX_PROFILE before requiring commercial preflight."
                ),
                details={"artwork": artwork_path},
            )
        source = Path(artwork_path)
        if not source.is_file():
            return PreflightResult(
                enabled=True,
                status=TOOL_ERROR,
                profile=profile,
                message=f"Artwork to preflight does not exist: {artwork_path}",
                details={"artwork": artwork_path},
            )
        if not Path(profile).is_file():
            return PreflightResult(
                enabled=True,
                status=NOT_CONFIGURED,
                profile=profile,
                message=f"Configured pdfToolbox profile does not exist: {profile}",
                details={"artwork": artwork_path},
            )

        work_dir = Path(output_dir) if output_dir else source.parent
        work_dir.mkdir(parents=True, exist_ok=True)
        report_path = work_dir / f"{source.stem}.pdftoolbox-report.json"
        corrected_path = work_dir / f"{source.stem}.corrected.pdf"

        command = [
            executable,
            "--profile",
            profile,
            "--report=JSON",
            f"--reportpath={report_path}",
        ]
        if self.config.fixup_profile:
            # Corrected output goes to a separate file; the original is preserved.
            command.append(f"--outputfile={corrected_path}")
        command.append(str(source))

        try:
            completed = self._execute(command)
        except subprocess.TimeoutExpired:
            return PreflightResult(
                enabled=True,
                status=TOOL_ERROR,
                profile=profile,
                message=f"pdfToolbox timed out after {self.config.timeout}s",
                details={"artwork": artwork_path, "command": command},
            )
        except (OSError, subprocess.SubprocessError) as error:
            return PreflightResult(
                enabled=True,
                status=TOOL_ERROR,
                profile=profile,
                message=f"Could not execute pdfToolbox CLI: {error}",
                details={"artwork": artwork_path, "command": command},
            )

        return self._normalize(
            completed=completed,
            profile=profile,
            artwork_path=str(source),
            report_path=report_path,
            corrected_path=corrected_path if self.config.fixup_profile else None,
            command=command,
        )

    def _normalize(
        self,
        *,
        completed: subprocess.CompletedProcess,
        profile: str,
        artwork_path: str,
        report_path: Path,
        corrected_path: Path | None,
        command: list[str],
    ) -> PreflightResult:
        details: dict[str, Any] = {
            "artwork": artwork_path,
            "command": command,
            "stdout": (completed.stdout or "")[-4000:],
            "stderr": (completed.stderr or "")[-4000:],
        }
        report: dict[str, Any] | None = None
        if report_path.is_file():
            try:
                report = json.loads(report_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as error:
                return PreflightResult(
                    enabled=True,
                    status=TOOL_ERROR,
                    profile=profile,
                    exit_code=completed.returncode,
                    report_path=str(report_path),
                    message=f"pdfToolbox report could not be parsed: {error}",
                    details=details,
                )
        if report is None:
            return PreflightResult(
                enabled=True,
                status=TOOL_ERROR,
                profile=profile,
                exit_code=completed.returncode,
                message="pdfToolbox produced no machine-readable report",
                details=details,
            )

        errors, warnings = _count_hits(report)
        corrected = (
            str(corrected_path)
            if corrected_path is not None and corrected_path.is_file()
            else None
        )
        if errors:
            status = FAIL
            message = f"pdfToolbox preflight reported {errors} error hit(s)"
        elif warnings:
            status = WARNING
            message = f"pdfToolbox preflight reported {warnings} warning hit(s)"
        elif completed.returncode != 0:
            status = TOOL_ERROR
            message = (
                f"pdfToolbox exited with code {completed.returncode} but reported no hits; "
                "verify the CLI exit-code semantics of the installed build"
            )
        else:
            status = PASS
            message = "pdfToolbox preflight passed with no errors or warnings"
        return PreflightResult(
            enabled=True,
            status=status,
            profile=profile,
            exit_code=completed.returncode,
            report_path=str(report_path),
            corrected_pdf=corrected,
            errors=errors,
            warnings=warnings,
            message=message,
            details=details,
        )


def _count_hits(report: dict[str, Any]) -> tuple[int, int]:
    """Count error and warning hits in a pdfToolbox JSON report.

    Report layouts differ between pdfToolbox builds, so both the aggregated summary
    counters and the per-hit severity list are inspected.
    """
    summary = report.get("summary")
    if isinstance(summary, dict):
        errors = _as_int(summary.get("errors"))
        warnings = _as_int(summary.get("warnings"))
        if errors is not None or warnings is not None:
            return errors or 0, warnings or 0

    error_count = 0
    warning_count = 0
    for hit in _iter_hits(report):
        severity = str(hit.get("severity") or hit.get("type") or "").strip().lower()
        if severity.startswith("error") or severity == "failure":
            error_count += 1
        elif severity.startswith("warn"):
            warning_count += 1
    return error_count, warning_count


def _iter_hits(report: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("hits", "results", "checks"):
        value = report.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def get_preflight_adapter(
    config: PdfToolboxConfig | None = None,
    runner: Any | None = None,
) -> PreflightAdapter:
    """Return the production pdfToolbox adapter for the current configuration."""
    return PdfToolboxAdapter(config=config, runner=runner)
