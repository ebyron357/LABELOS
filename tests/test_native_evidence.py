"""Native-build evidence gate and package-integrity regression tests.

Every artifact below is a synthetic test fixture written into ``tmp_path``. None of it is
production evidence: real Illustrator artwork, previews, logs, and layer/object results are
operator-side outputs that this repository does not contain and must never fabricate.
"""

import json
from pathlib import Path

import pytest

from labelos.evidence import CHECK_NAME
from labelos.models import LabelSpec
from labelos.package import BLOCKED_REQUIREMENTS, create_package, verify_package
from labelos.validate import validate

ROOT = Path(__file__).parent.parent
ARTWORK = str(ROOT / "fixtures/passing-label.svg")

VALID_EVIDENCE = {
    "missing_layers": [],
    "layers": ["Dieline", "Regulatory"],
    "objects": ["net_weight_box"],
    "reopened_without_repair": True,
}


def write_evidence(root: Path, *, data=..., log="native build complete\nPASSED\n") -> dict:
    """Write a synthetic evidence set and return the ``native_evidence`` config block."""
    (root / "evidence").mkdir(exist_ok=True)
    if data is not ...:
        payload = data if isinstance(data, str) else json.dumps(data)
        (root / "evidence/build.json").write_text(payload, encoding="utf-8")
    else:
        (root / "evidence/build.json").write_text(json.dumps(VALID_EVIDENCE), encoding="utf-8")
    if log is not None:
        (root / "evidence/build.log").write_text(log, encoding="utf-8")
    (root / "evidence/preview.png").write_bytes(b"\x89PNG\r\n\x1a\nsynthetic-preview")
    (root / "evidence/label.ai").write_bytes(b"%PDF-1.6 synthetic-native-artwork")
    return {
        "evidence_json": "evidence/build.json",
        "log": "evidence/build.log",
        "preview_png": "evidence/preview.png",
        "native_artwork": "evidence/label.ai",
        "required_layers": ["Dieline", "Regulatory"],
        "required_objects": ["net_weight_box"],
    }


def spec_for(root: Path, native_evidence: dict | None) -> LabelSpec:
    config = {"artwork": ARTWORK, "width_mm": 100, "height_mm": 50, "bleed_mm": 3}
    if native_evidence is not None:
        config["native_evidence"] = native_evidence
    return LabelSpec.from_dict(config, root)


def codes(report) -> list[str]:
    return [issue.code for issue in report.issues if issue.severity == "error"]


def gate(tmp_path, **kwargs):
    """Validate a label whose evidence set is built from ``kwargs``."""
    return validate(spec_for(tmp_path, write_evidence(tmp_path, **kwargs)))


# --------------------------------------------------------------------------- passing case


def test_valid_native_evidence_passes(tmp_path):
    report = gate(tmp_path)
    assert report.passed, codes(report)
    assert CHECK_NAME in report.checks
    artifacts = report.metadata["native_evidence"]["artifacts"]
    assert sorted(artifacts) == ["evidence_json", "log", "native_artwork", "preview_png"]
    assert all(len(entry["sha256"]) == 64 and entry["bytes"] > 0 for entry in artifacts.values())


def test_label_without_native_evidence_does_not_run_the_gate(tmp_path):
    report = validate(spec_for(tmp_path, None))
    assert report.passed
    assert CHECK_NAME not in report.checks
    assert "native_evidence" not in report.metadata


# ------------------------------------------------------------------- missing artifacts


def test_missing_evidence_file_fails(tmp_path):
    block = write_evidence(tmp_path)
    (tmp_path / "evidence/build.json").unlink()
    report = validate(spec_for(tmp_path, block))
    assert not report.passed
    assert codes(report) == ["EVIDENCE_ARTIFACT_MISSING"]


@pytest.mark.parametrize("role", ["evidence_json", "log", "preview_png", "native_artwork"])
def test_undeclared_artifact_fails(tmp_path, role):
    block = write_evidence(tmp_path)
    del block[role]
    report = validate(spec_for(tmp_path, block))
    assert not report.passed
    assert "EVIDENCE_ARTIFACT_MISSING" in codes(report)


def test_missing_log_file_fails(tmp_path):
    block = write_evidence(tmp_path)
    (tmp_path / "evidence/build.log").unlink()
    report = validate(spec_for(tmp_path, block))
    assert codes(report) == ["EVIDENCE_ARTIFACT_MISSING"]


# ------------------------------------------------------------------------- invalid JSON


@pytest.mark.parametrize("payload", ["", "{", "not json", "[]", "null", '"PASSED"', "123"])
def test_malformed_evidence_json_fails(tmp_path, payload):
    report = gate(tmp_path, data=payload)
    assert not report.passed
    assert "EVIDENCE_INVALID_JSON" in codes(report)


# ------------------------------------------------------------------------ layer evidence


def test_missing_layers_key_absent_fails(tmp_path):
    data = {key: value for key, value in VALID_EVIDENCE.items() if key != "missing_layers"}
    report = gate(tmp_path, data=data)
    assert not report.passed
    assert "NATIVE_LAYERS_MISSING" in codes(report)


def test_missing_layers_non_empty_fails(tmp_path):
    report = gate(tmp_path, data={**VALID_EVIDENCE, "missing_layers": ["Regulatory"]})
    assert not report.passed
    assert "NATIVE_LAYERS_MISSING" in codes(report)


@pytest.mark.parametrize("value", ["", "none", {}, 0, False, None, [1, 2]])
def test_missing_layers_wrong_type_fails(tmp_path, value):
    report = gate(tmp_path, data={**VALID_EVIDENCE, "missing_layers": value})
    assert not report.passed
    assert "NATIVE_LAYERS_MISSING" in codes(report)


def test_required_layer_without_positive_listing_fails(tmp_path):
    data = {key: value for key, value in VALID_EVIDENCE.items() if key != "layers"}
    report = gate(tmp_path, data=data)
    assert not report.passed
    assert "NATIVE_LAYERS_MISSING" in codes(report)


def test_required_layer_absent_from_positive_listing_fails(tmp_path):
    report = gate(tmp_path, data={**VALID_EVIDENCE, "layers": ["Dieline"]})
    assert not report.passed
    assert "NATIVE_LAYERS_MISSING" in codes(report)


def test_required_layer_flagged_false_fails(tmp_path):
    layers = {"Dieline": True, "Regulatory": False}
    report = gate(tmp_path, data={**VALID_EVIDENCE, "layers": layers})
    assert not report.passed
    assert "NATIVE_LAYERS_MISSING" in codes(report)


def test_required_layer_confirmed_by_mapping_passes(tmp_path):
    layers = {"Dieline": True, "Regulatory": True}
    report = gate(tmp_path, data={**VALID_EVIDENCE, "layers": layers})
    assert report.passed, codes(report)


@pytest.mark.parametrize("layers", [{"Regulatory": "true"}, {"Regulatory": 1}, "Regulatory", 7])
def test_layer_listing_truthy_but_not_boolean_fails(tmp_path, layers):
    report = gate(tmp_path, data={**VALID_EVIDENCE, "layers": layers})
    assert not report.passed
    assert "NATIVE_LAYERS_MISSING" in codes(report)


# ------------------------------------------------------------------------ named objects


def test_required_object_absent_fails(tmp_path):
    data = {key: value for key, value in VALID_EVIDENCE.items() if key != "objects"}
    report = gate(tmp_path, data=data)
    assert not report.passed
    assert "NAMED_OBJECTS_MISSING" in codes(report)


def test_required_object_not_listed_fails(tmp_path):
    report = gate(tmp_path, data={**VALID_EVIDENCE, "objects": ["other_box"]})
    assert not report.passed
    assert "NAMED_OBJECTS_MISSING" in codes(report)


def test_required_object_flagged_false_fails(tmp_path):
    report = gate(tmp_path, data={**VALID_EVIDENCE, "objects": {"net_weight_box": False}})
    assert not report.passed
    assert "NAMED_OBJECTS_MISSING" in codes(report)


# ---------------------------------------------------------------------- reopen evidence


@pytest.mark.parametrize("value", [False, "true", "PASSED", 1, None, [], {}])
def test_reopen_not_proven_fails(tmp_path, value):
    report = gate(tmp_path, data={**VALID_EVIDENCE, "reopened_without_repair": value})
    assert not report.passed
    assert "NATIVE_REOPEN_UNPROVEN" in codes(report)


def test_reopen_key_absent_fails(tmp_path):
    data = {k: v for k, v in VALID_EVIDENCE.items() if k != "reopened_without_repair"}
    report = gate(tmp_path, data=data)
    assert not report.passed
    assert "NATIVE_REOPEN_UNPROVEN" in codes(report)


# --------------------------------------------------------------------------- log parsing


@pytest.mark.parametrize(
    "log",
    ["", "   \n\n", "FAILED\n", "PASSED\nFAILED\n", "passed\n", "PASSED WITH WARNINGS\n", "\n"],
)
def test_log_not_passed_fails(tmp_path, log):
    report = gate(tmp_path, log=log)
    assert not report.passed
    assert "EVIDENCE_LOG_NOT_PASSED" in codes(report)


@pytest.mark.parametrize("log", ["PASSED", "PASSED\n", "step\nPASSED  \n\n\n", "step\n  PASSED\t\n"])
def test_log_trailing_whitespace_and_blank_lines_pass(tmp_path, log):
    report = gate(tmp_path, log=log)
    assert report.passed, codes(report)


# ------------------------------------------------------------------------- unsafe paths


@pytest.mark.parametrize(
    "declared",
    ["../outside.json", "evidence/../../outside.json", "/etc/passwd", "./../build.json"],
)
def test_unsafe_evidence_path_fails(tmp_path, declared):
    block = write_evidence(tmp_path)
    block["evidence_json"] = declared
    report = validate(spec_for(tmp_path, block))
    assert not report.passed
    assert "EVIDENCE_PATH_UNSAFE" in codes(report)


def test_directory_declared_as_evidence_fails(tmp_path):
    block = write_evidence(tmp_path)
    block["evidence_json"] = "evidence"
    report = validate(spec_for(tmp_path, block))
    assert not report.passed
    assert codes(report) == ["EVIDENCE_ARTIFACT_MISSING"]


def test_symlinked_evidence_path_fails(tmp_path):
    block = write_evidence(tmp_path)
    (tmp_path / "evidence/linked.json").symlink_to(tmp_path / "evidence/build.json")
    block["evidence_json"] = "evidence/linked.json"
    report = validate(spec_for(tmp_path, block))
    assert not report.passed
    assert codes(report) == ["EVIDENCE_PATH_UNSAFE"]


def test_symlinked_evidence_directory_fails(tmp_path):
    block = write_evidence(tmp_path)
    (tmp_path / "linked").symlink_to(tmp_path / "evidence", target_is_directory=True)
    block["log"] = "linked/build.log"
    report = validate(spec_for(tmp_path, block))
    assert not report.passed
    assert codes(report) == ["EVIDENCE_PATH_UNSAFE"]


# ------------------------------------------------------------------- configuration schema


def test_unknown_native_evidence_field_is_rejected(tmp_path):
    block = write_evidence(tmp_path)
    block["required_layer"] = ["Typo"]
    with pytest.raises(ValueError, match="Unknown native_evidence fields"):
        spec_for(tmp_path, block)


@pytest.mark.parametrize("value", [["", "A"], "Dieline", [1], ["A", "A"]])
def test_required_layers_must_be_unique_non_empty_names(tmp_path, value):
    block = write_evidence(tmp_path)
    block["required_layers"] = value
    with pytest.raises(ValueError):
        spec_for(tmp_path, block)


def test_native_evidence_must_be_an_object(tmp_path):
    with pytest.raises(TypeError):
        spec_for(tmp_path, ["evidence/build.json"])


# -------------------------------------------------------------------------- packaging


def test_packaging_is_refused_when_the_gate_fails(tmp_path):
    spec = spec_for(tmp_path, write_evidence(tmp_path, log="FAILED\n"))
    report = validate(spec)
    with pytest.raises(ValueError, match="validation errors"):
        create_package(spec, report, tmp_path / "release")
    assert not (tmp_path / "release").exists()


def test_packaging_is_refused_when_the_gate_did_not_run(tmp_path):
    spec = spec_for(tmp_path, write_evidence(tmp_path))
    report = validate(spec_for(tmp_path, None))
    with pytest.raises(ValueError, match="native evidence gate did not run"):
        create_package(spec, report, tmp_path / "release")


def test_evidence_changed_after_validation_is_refused(tmp_path):
    spec = spec_for(tmp_path, write_evidence(tmp_path))
    report = validate(spec)
    assert report.passed
    (tmp_path / "evidence/build.log").write_text("FAILED\n", encoding="utf-8")
    with pytest.raises(ValueError, match="changed after validation"):
        create_package(spec, report, tmp_path / "release")
    assert not (tmp_path / "release").exists()


def test_manifest_records_evidence_hashes_and_byte_counts(tmp_path):
    spec = spec_for(tmp_path, write_evidence(tmp_path))
    report = validate(spec)
    manifest_path = create_package(spec, report, tmp_path / "release")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = {entry["role"]: entry for entry in manifest["native_evidence"]}
    assert sorted(entries) == ["evidence_json", "log", "native_artwork", "preview_png"]
    validated = report.metadata["native_evidence"]["artifacts"]
    for role, entry in entries.items():
        packaged = manifest_path.parent / entry["file"]
        assert entry["file"].startswith("native-evidence/")
        assert packaged.is_file()
        assert entry["sha256"] == validated[role]["sha256"]
        assert entry["bytes"] == packaged.stat().st_size
    assert not verify_package(manifest_path.parent)


def test_blocked_requirements_survive_a_passing_evidence_gate(tmp_path):
    spec = spec_for(tmp_path, write_evidence(tmp_path))
    manifest_path = create_package(spec, validate(spec), tmp_path / "release")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert sorted(manifest["blocked_requirements"]) == sorted(BLOCKED_REQUIREMENTS)
    assert sorted(BLOCKED_REQUIREMENTS) == [
        "icc_profile",
        "printer_profile",
        "production_pdf",
        "regulatory_approval",
    ]


# ------------------------------------------------------------------- tamper detection


def packaged(tmp_path) -> Path:
    spec = spec_for(tmp_path, write_evidence(tmp_path))
    return create_package(spec, validate(spec), tmp_path / "release").parent


def test_modified_evidence_bytes_are_detected(tmp_path):
    release = packaged(tmp_path)
    (release / "native-evidence/log/build.log").write_text("PASSED\n", encoding="utf-8")
    assert any("checksum mismatch" in failure for failure in verify_package(release))


def test_deleted_evidence_file_is_detected(tmp_path):
    release = packaged(tmp_path)
    (release / "native-evidence/evidence_json/build.json").unlink()
    assert any("is missing" in failure for failure in verify_package(release))


def test_added_evidence_file_is_detected(tmp_path):
    release = packaged(tmp_path)
    (release / "native-evidence/log/extra.log").write_text("PASSED\n", encoding="utf-8")
    assert any("not recorded in the manifest" in f for f in verify_package(release))


def test_evidence_replaced_by_symlink_is_detected(tmp_path):
    release = packaged(tmp_path)
    target = release / "native-evidence/log/build.log"
    target.unlink()
    target.symlink_to(release / "native-evidence/evidence_json/build.json")
    assert any("symbolic link" in f or "is missing" in f for f in verify_package(release))


def test_manifest_stripped_of_evidence_is_detected(tmp_path):
    release = packaged(tmp_path)
    manifest_path = release / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["native_evidence"] = []
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    failures = verify_package(release)
    assert any("not packaged" in f for f in failures)
    assert any("not recorded in the manifest" in f for f in failures)


def test_manifest_with_forged_digest_is_detected(tmp_path):
    release = packaged(tmp_path)
    manifest_path = release / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for entry in manifest["native_evidence"]:
        if entry["role"] == "log":
            entry["sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    assert any("checksum mismatch" in f for f in verify_package(release))


def test_manifest_with_duplicate_evidence_entry_is_detected(tmp_path):
    release = packaged(tmp_path)
    manifest_path = release / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["native_evidence"].append(dict(manifest["native_evidence"][0]))
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    assert any("recorded more than once" in f for f in verify_package(release))


def test_manifest_evidence_path_traversal_is_detected(tmp_path):
    release = packaged(tmp_path)
    manifest_path = release / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["native_evidence"][0]["file"] = "../outside.bin"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    assert any("unsafe" in f for f in verify_package(release))


def test_manifest_artwork_path_traversal_is_detected(tmp_path):
    release = packaged(tmp_path)
    manifest_path = release / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["artwork"]["file"] = "../../etc/passwd"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    assert any("artwork path is unsafe" in f for f in verify_package(release))


def test_manifest_evidence_entry_repointed_at_another_file_is_detected(tmp_path):
    release = packaged(tmp_path)
    manifest_path = release / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for entry in manifest["native_evidence"]:
        if entry["role"] == "log":
            entry["file"] = "passing-label.svg"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    failures = verify_package(release)
    assert any("checksum mismatch" in f for f in failures)
    assert any("not recorded in the manifest" in f for f in failures)


def test_manifest_without_blocked_requirements_is_detected(tmp_path):
    release = packaged(tmp_path)
    manifest_path = release / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["blocked_requirements"] = ["printer_profile"]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    assert any("blocked_requirements" in f for f in verify_package(release))
