# callas pdfToolbox setup

LABELOS drives the **licensed callas pdfToolbox CLI**. LABELOS never bundles, vendors, or
emulates pdfToolbox, and never reports a preflight pass that pdfToolbox did not produce.

## Configuration

All configuration is environment-based so no workstation-specific path is committed:

| Variable | Required | Purpose |
| --- | --- | --- |
| `LABELOS_PDFTOOLBOX_PATH` | yes | Absolute path of the licensed pdfToolbox CLI executable |
| `LABELOS_PDFTOOLBOX_PROFILE` | yes | Absolute path of the approved preflight profile (`.kfpx`) |
| `LABELOS_PDFTOOLBOX_FIXUP_PROFILE` | no | Approved fixup profile; enables corrected-PDF output |
| `LABELOS_PDFTOOLBOX_TIMEOUT` | no | CLI timeout in seconds (default `300`) |

Set them in the machine-local `.env` (git-ignored) or the service environment. Never commit
the executable, the licence, or the profile.

## Result semantics

`labelos.preflight` normalizes every run into exactly one status:

| Status | Meaning | Blocks release |
| --- | --- | --- |
| `PASS` | Profile executed, no error or warning hits | no |
| `WARNING` | Profile executed, warning hits only | no |
| `FAIL` | Profile executed, error hits present | **yes** |
| `TOOL_ERROR` | CLI could not run, timed out, or produced no parsable report | **yes** |
| `NOT_CONFIGURED` | Executable/profile not configured or not installed | **yes** |

`ProductionService.run_preflight(job_id, required=True)` fails closed on any blocking status
and records the machine-readable result on the job (and therefore in the release record).

## Original artwork is never overwritten

The source PDF is passed as input only. When a fixup profile is configured, the corrected PDF
is written next to the source as `<name>.corrected.pdf` and the JSON report as
`<name>.pdftoolbox-report.json`. Both are recorded on the job.

## Operator verification (required before production use)

On the workstation with the licensed CLI installed, run the applicable equivalents for the
installed build and record the output:

```bash
"$LABELOS_PDFTOOLBOX_PATH" --version
"$LABELOS_PDFTOOLBOX_PATH" --status
"$LABELOS_PDFTOOLBOX_PATH" --help
labelos doctor --json      # pdftoolbox component must report "ready"
```

Exact flag spelling follows the installed pdfToolbox build. If the build's report flags or
exit-code semantics differ from `--report=JSON` / `--reportpath=` / `--outputfile=`, update
`labelos/preflight.py` accordingly and re-run the test suite.

## CI note

`tests/test_closeout_hardening.py` exercises the adapter through a controlled command
execution boundary. Those tests prove the LABELOS-side contract (command construction,
report parsing, status normalization, corrected-output separation, fail-closed behavior).
**They are not proof that the licensed pdfToolbox CLI works** — that requires the operator
verification above.
