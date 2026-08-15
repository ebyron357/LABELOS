"""Native-evidence gate tests.

Every fixture built here is synthetic test input, not production evidence. LABELOS
does not generate Illustrator artefacts; a real run must be supplied by the operator.
"""

import json
from pathlib import Path

import pytest

from labelos.models import LabelSpec, Report
from labelos.package import BLOCKED_REQUIREMENTS, create_package, verify_package
from labelos.validate import validate

ROOT = Path(__file__).parent.parent
ARTWORK = ROOT / "fixtures/passing-label.svg"

VALID_DOCUMENT = {
    "missing_layers": [],
    "layers": ["Dieline", "Artwork", "Varnish"],
    "named_objects": ["dieline_path", "barcode_group"],
    "reopened_without_repair": True,
}


def build(tmp_path, *, document=VALID_DOCUMENT, log="native build\nPASSED\n", block=None):
    """Write a synthetic evidence bundle and return its LabelSpec."""
    (tmp_path / "passing-label.svg").write_text(
        ARTWORK.read_text(encoding="utf-8"), encoding="utf-8"
    )
    (tmp_path / "preview.png").write_bytes(b"\x89PNG\r\n\x1a\nsynthetic-preview")
    (tmp_path / "native.ai").write_bytes(b"synthetic-native-artwork")
    if document is not None:
        (tmp_path / "evidence.json").write_text(json.dumps(document), encoding="utf-8")
    if log is not None:
        (tmp_path / "build.log").write_text(log, encoding="utf-8")
    native_evidence = {
        "evidence_json": "evidence.json",
        "log": "build.log",
        "preview_png": "preview.png",
        "native_artwork": "native.ai",
        "required_layers": ["Dieline", "Artwork"],
        "required_objects": ["dieline_path"],
    }
    native_evidence.update(block or {})
    return LabelSpec.from_dict(
        {
            "artwork": "passing-label.svg",
            "width_mm": 100,
            "height_mm": 50,
            "bleed_mm": 3,
            "native_evidence": native_evidence,
        },
        tmp_path,
    )


def codes(report):
    return {issue.code for issue in report.issues if issue.severity == "error"}


def test_valid_native_evidence_passes(tmp_path):
    report = validate(build(tmp_path))
    assert report.passed
    assert "native-evidence" in report.checks
    assert report.metadata["native_evidence"]["required_layers"] == ["Dieline", "Artwork"]


def test_label_without_evidence_block_is_unaffected(tmp_path):
    spec = LabelSpec.from_dict(
        {"artwork": str(ARTWORK), "width_mm": 106, "height_mm": 56}, tmp_path
    )
    report = validate(spec)
    assert report.passed
    assert "native-evidence" not in report.checks


def test_evidence_gate_runs_even_when_artwork_is_missing(tmp_path):
    """Artwork failures must not short-circuit the evidence gate."""
    spec = build(tmp_path, log="FAILED\n")
    (tmp_path / "passing-label.svg").unlink()
    assert codes(validate(spec)) == {"ARTWORK_MISSING", "EVIDENCE_LOG_NOT_PASSED"}


def test_evidence_json_absent_fails(tmp_path):
    report = validate(build(tmp_path, document=None))
    assert not report.passed
    assert codes(report) == {"EVIDENCE_ARTIFACT_MISSING"}


@pytest.mark.parametrize("omitted", ["evidence_json", "log"])
def test_undeclared_required_artifact_fails(tmp_path, omitted):
    """An evidence block that simply omits a required artifact must not pass."""
    spec = build(tmp_path)
    declared = {
        key: value for key, value in spec.native_evidence.declared().items() if key != omitted
    }
    spec = LabelSpec.from_dict(
        {
            "artwork": "passing-label.svg",
            "width_mm": 100,
            "height_mm": 50,
            "bleed_mm": 3,
            "native_evidence": declared,
        },
        tmp_path,
    )
    assert codes(validate(spec)) == {"EVIDENCE_ARTIFACT_MISSING"}


def test_referenced_artifact_missing_fails(tmp_path):
    spec = build(tmp_path)
    (tmp_path / "native.ai").unlink()
    assert codes(validate(spec)) == {"EVIDENCE_ARTIFACT_MISSING"}


def test_malformed_evidence_json_fails(tmp_path):
    spec = build(tmp_path)
    (tmp_path / "evidence.json").write_text("{not json", encoding="utf-8")
    assert codes(validate(spec)) == {"EVIDENCE_INVALID_JSON"}


def test_evidence_json_array_root_fails(tmp_path):
    spec = build(tmp_path)
    (tmp_path / "evidence.json").write_text("[]", encoding="utf-8")
    assert codes(validate(spec)) == {"EVIDENCE_INVALID_JSON"}


def test_unreadable_evidence_json_is_reported_not_raised(tmp_path, monkeypatch):
    """An OS-level read failure must become a report error, not an exception."""
    spec = build(tmp_path)
    original = Path.read_text

    def deny(self, *args, **kwargs):
        if self.name == "evidence.json":
            raise PermissionError(13, "Permission denied")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", deny)
    assert codes(validate(spec)) == {"EVIDENCE_INVALID_JSON"}


def test_unreadable_log_is_reported_not_raised(tmp_path, monkeypatch):
    spec = build(tmp_path)
    original = Path.read_text

    def deny(self, *args, **kwargs):
        if self.name == "build.log":
            raise PermissionError(13, "Permission denied")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", deny)
    assert codes(validate(spec)) == {"EVIDENCE_LOG_NOT_PASSED"}


def test_log_with_invalid_utf8_fails(tmp_path):
    spec = build(tmp_path)
    (tmp_path / "build.log").write_bytes(b"\xff\xfe\x00PASSED")
    assert codes(validate(spec)) == {"EVIDENCE_LOG_NOT_PASSED"}


def test_missing_layers_key_omitted_fails(tmp_path):
    document = {key: value for key, value in VALID_DOCUMENT.items() if key != "missing_layers"}
    assert "NATIVE_LAYERS_MISSING" in codes(validate(build(tmp_path, document=document)))


def test_missing_layers_non_empty_fails(tmp_path):
    document = dict(VALID_DOCUMENT, missing_layers=["Varnish"])
    assert codes(validate(build(tmp_path, document=document))) == {"NATIVE_LAYERS_MISSING"}


def test_required_layer_without_positive_confirmation_fails(tmp_path):
    document = dict(VALID_DOCUMENT, layers=["Artwork"])
    assert codes(validate(build(tmp_path, document=document))) == {"NATIVE_LAYERS_MISSING"}


def test_layers_key_omitted_fails_when_layers_required(tmp_path):
    document = {key: value for key, value in VALID_DOCUMENT.items() if key != "layers"}
    assert codes(validate(build(tmp_path, document=document))) == {"NATIVE_LAYERS_MISSING"}


def test_required_named_object_absent_fails(tmp_path):
    document = dict(VALID_DOCUMENT, named_objects=["barcode_group"])
    assert codes(validate(build(tmp_path, document=document))) == {"NAMED_OBJECTS_MISSING"}


def test_named_objects_key_omitted_fails(tmp_path):
    document = {key: value for key, value in VALID_DOCUMENT.items() if key != "named_objects"}
    assert codes(validate(build(tmp_path, document=document))) == {"NAMED_OBJECTS_MISSING"}


@pytest.mark.parametrize("value", [False, "true", "PASSED", 1, None, [], {}])
def test_reopen_without_repair_must_be_boolean_true(tmp_path, value):
    document = dict(VALID_DOCUMENT, reopened_without_repair=value)
    assert codes(validate(build(tmp_path, document=document))) == {"NATIVE_REOPEN_UNPROVEN"}


def test_reopen_without_repair_omitted_fails(tmp_path):
    document = {
        key: value for key, value in VALID_DOCUMENT.items() if key != "reopened_without_repair"
    }
    assert codes(validate(build(tmp_path, document=document))) == {"NATIVE_REOPEN_UNPROVEN"}


@pytest.mark.parametrize("log", ["", "   \n\n", "PASSED\nFAILED\n", "passed\n", "PASSED extra\n"])
def test_log_not_ending_in_passed_fails(tmp_path, log):
    assert codes(validate(build(tmp_path, log=log))) == {"EVIDENCE_LOG_NOT_PASSED"}


def test_log_trailing_whitespace_and_blank_lines_are_tolerated(tmp_path):
    assert validate(build(tmp_path, log="step 1\n  PASSED  \n\n   \n")).passed


def test_log_file_absent_fails(tmp_path):
    assert codes(validate(build(tmp_path, log=None))) == {"EVIDENCE_ARTIFACT_MISSING"}


def test_path_traversal_is_rejected(tmp_path):
    outside = tmp_path.parent / "outside.json"
    outside.write_text(json.dumps(VALID_DOCUMENT), encoding="utf-8")
    spec = build(tmp_path, block={"evidence_json": "../outside.json"})
    assert codes(validate(spec)) == {"EVIDENCE_PATH_UNSAFE"}


def test_absolute_evidence_path_is_rejected(tmp_path):
    spec = build(tmp_path, block={"evidence_json": str(tmp_path / "evidence.json")})
    assert codes(validate(spec)) == {"EVIDENCE_PATH_UNSAFE"}


def test_symlinked_evidence_is_rejected(tmp_path):
    outside = tmp_path.parent / "linked.log"
    outside.write_text("PASSED\n", encoding="utf-8")
    link = tmp_path / "linked.log"
    link.symlink_to(outside)
    assert codes(validate(build(tmp_path, block={"log": "linked.log"}))) == {
        "EVIDENCE_PATH_UNSAFE"
    }


def test_unknown_evidence_field_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="Unknown native_evidence fields"):
        build(tmp_path, block={"required_layerz": ["Dieline"]})


def test_package_records_evidence_hashes_and_bytes(tmp_path):
    spec = build(tmp_path)
    report = validate(spec)
    manifest_path = create_package(spec, report, tmp_path / "release")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    recorded = manifest["native_evidence"]
    assert set(recorded) == {"evidence_json", "log", "preview_png", "native_artwork"}
    for key, entry in recorded.items():
        packaged = manifest_path.parent / entry["file"]
        assert packaged.is_file(), key
        assert entry["bytes"] == packaged.stat().st_size
        assert len(entry["sha256"]) == 64
    assert not verify_package(manifest_path.parent)


def test_package_is_refused_when_evidence_fails(tmp_path):
    spec = build(tmp_path, log="FAILED\n")
    report = validate(spec)
    destination = tmp_path / "release"
    with pytest.raises(ValueError, match="validation errors"):
        create_package(spec, report, destination)
    assert not destination.exists()


def test_package_is_refused_when_evidence_names_collide(tmp_path):
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested/evidence.json").write_text(
        json.dumps(VALID_DOCUMENT), encoding="utf-8"
    )
    spec = build(tmp_path, block={"native_artwork": "nested/evidence.json"})
    report = validate(spec)
    destination = tmp_path / "release"
    with pytest.raises(ValueError, match="share file names"):
        create_package(spec, report, destination)
    assert not destination.exists()


def test_package_rejects_a_report_that_never_ran_the_gate(tmp_path):
    """Packaging re-runs the gate instead of trusting the report it is handed."""
    spec = build(tmp_path, log="FAILED\n")
    forged = Report(source=str(spec.artwork))
    assert forged.passed
    destination = tmp_path / "release"
    with pytest.raises(ValueError, match="unverified native evidence"):
        create_package(spec, forged, destination)
    assert not destination.exists()


def test_packaged_evidence_tampering_is_detected(tmp_path):
    spec = build(tmp_path)
    manifest_path = create_package(spec, validate(spec), tmp_path / "release")
    package = manifest_path.parent
    (package / "native-evidence/build.log").write_text("FAILED\n", encoding="utf-8")
    assert verify_package(package) == ["native_evidence.log checksum mismatch: native-evidence/build.log"]


def test_evidence_replaced_by_symlink_is_detected(tmp_path):
    spec = build(tmp_path)
    manifest_path = create_package(spec, validate(spec), tmp_path / "release")
    package = manifest_path.parent
    packaged = package / "native-evidence/build.log"
    packaged.unlink()
    packaged.symlink_to(tmp_path / "build.log")
    assert verify_package(package) == [
        "native_evidence.log manifest entry has an unsafe file path: native-evidence/build.log"
    ]


def test_removed_packaged_evidence_is_detected(tmp_path):
    spec = build(tmp_path)
    manifest_path = create_package(spec, validate(spec), tmp_path / "release")
    package = manifest_path.parent
    (package / "native-evidence/preview.png").unlink()
    assert verify_package(package) == [
        "native_evidence.preview_png file is missing: native-evidence/preview.png"
    ]


def test_unrecorded_packaged_evidence_is_detected(tmp_path):
    spec = build(tmp_path)
    manifest_path = create_package(spec, validate(spec), tmp_path / "release")
    package = manifest_path.parent
    (package / "native-evidence/extra.json").write_text("{}", encoding="utf-8")
    assert verify_package(package) == [
        "native-evidence contains an unrecorded file: native-evidence/extra.json"
    ]


def test_manifest_records_blocked_requirements(tmp_path):
    spec = build(tmp_path)
    manifest_path = create_package(spec, validate(spec), tmp_path / "release")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["blocked_requirements"] == [
        "icc_profile",
        "printer_profile",
        "production_pdf",
        "regulatory_approval",
    ]
    assert set(BLOCKED_REQUIREMENTS) == set(manifest["blocked_requirements"])


def test_clearing_blocked_requirements_fails_verification(tmp_path):
    spec = build(tmp_path)
    manifest_path = create_package(spec, validate(spec), tmp_path / "release")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["blocked_requirements"] = []
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    assert verify_package(manifest_path.parent) == [
        (
            "blocked_requirements must record every external blocker: "
            "icc_profile, printer_profile, production_pdf, regulatory_approval"
        )
    ]
