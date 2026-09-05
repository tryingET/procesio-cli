from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "run-procesio-control-tower-phase06-frozen.py"


def _load():
    spec = importlib.util.spec_from_file_location(
        "run_procesio_control_tower_phase06_frozen", SCRIPT
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _skill(path: Path) -> Path:
    path.mkdir(parents=True)
    (path / "SKILL.md").write_text("---\nname: procesio-cli\n---\n", encoding="utf-8")
    return path


def _write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _phase(module, phase_id: str, status: str, *, summary: str = "") -> dict:
    return {
        "schema_version": 1,
        "project_id": module.PROJECT_ID,
        "phase": phase_id,
        "status": status,
        "summary": summary,
        "checks": [],
        "gaps": [],
        "unknown_outcomes": [],
        "next_phase_safe": True,
    }


def _completed_phase06_run(tmp_path: Path, module, *, local_gap: bool = False) -> Path:
    run_root = tmp_path / "run"
    phase03 = _phase(
        module,
        module.PHASE03_ID,
        "passed_with_gap",
        summary="Custom connector unavailable; verified Call API fallback retained.",
    )
    phase03["gaps"] = [
        {
            "id": "custom-connector-fallback",
            "message": "Custom connector unavailable; Call API fallback verified.",
        }
    ]
    phase05 = _phase(module, module.PHASE05_ID, "passed")
    phase06 = _phase(module, module.PHASE06_ID, "passed_with_gap")
    phase06["checks"] = [
        {"id": "inventory_verified", "passed": True, "evidence": "inventory.json"},
        {"id": "exports_verified", "passed": True, "evidence": "export hashes"},
    ]
    phase06["gaps"] = [
        {
            "id": "local-form-gap" if local_gap else "custom-connector-fallback",
            "message": (
                "Native form result is still broken."
                if local_gap
                else "Custom connector unavailable; Call API fallback retained."
            ),
        }
    ]
    _write(run_root / f"phases/{module.PHASE03_ID}.json", phase03)
    _write(run_root / f"phases/{module.PHASE05_ID}.json", phase05)
    _write(run_root / f"phases/{module.PHASE06_ID}.json", phase06)
    _write(
        run_root / "final-report.json",
        {
            "project_status": "passed_with_gap",
            "phase_verdicts": [
                {"phase": module.PHASE06_ID, "status": "passed_with_gap"}
            ],
            "remaining_gaps": phase06["gaps"],
        },
    )
    _write(run_root / "deployment.json", {"schema_version": 1})
    export = run_root / "export"
    export.mkdir(parents=True)
    (export / "control-tower-retained.procesio").write_bytes(b"bundle")
    (export / "evidence-ledger.csv").write_text(
        "Evidence Key\nkey-1\n", encoding="utf-8"
    )
    return run_root


def _rotation_attestation(run_root: Path, module) -> dict:
    attestation = {
        "schema_version": 1,
        "kind": "procesio-control-tower-token-rotation-attestation",
        "project_id": module.PROJECT_ID,
        "remediation_id": module.ROTATION_REMEDIATION_ID,
        "status": "passed",
        "redaction_erased_incident": False,
        "old_token_revoked": True,
        "replacement_token_proven": True,
        "secret_scan_clean": True,
        "phase05_security_lineage_updated": True,
        "phase06_artifacts_invalidated": True,
        "new_token_sha256": "b" * 64,
    }
    _write(run_root / module.ROTATION_ATTESTATION_RELATIVE, attestation)
    phase05 = _phase(module, module.PHASE05_ID, "passed")
    phase05["security_remediation"] = {
        "remediation_id": module.ROTATION_REMEDIATION_ID,
        "incident": "clear_token_printed_to_agent_transcript",
        "new_token_sha256": attestation["new_token_sha256"],
    }
    _write(run_root / f"phases/{module.PHASE05_ID}.json", phase05)
    return attestation


def test_helper_is_uv_script_and_requires_separate_confirmation(capsys):
    text = SCRIPT.read_text(encoding="utf-8")
    assert text.startswith("#!/usr/bin/env -S uv run --script")
    assert '# requires-python = ">=3.11"' in text
    module = _load()

    code = module.main(
        [
            "--model",
            "zai/glm-5.3",
            "--thinking",
            "high",
            "--max-hours",
            "1",
        ]
    )
    assert code == 2
    result = json.loads(capsys.readouterr().out)
    assert result["error"]["code"] == "confirmation_required"
    assert module.CONFIRMATION in result["error"]["message"]


def test_install_execution_skill_preserves_metadata_and_scopes_phase06_status(tmp_path):
    helper = _load()
    original = _skill(tmp_path / "original")
    frozen = _skill(tmp_path / "frozen")
    contract = tmp_path / "contract"
    manifest = tmp_path / "manifest"
    seeds = tmp_path / "seeds"
    openapi = tmp_path / "openapi"
    for path in (contract, manifest, seeds, openapi):
        path.write_text("x", encoding="utf-8")

    module = SimpleNamespace(
        SKILL=original,
        CONTRACT=contract,
        MANIFEST=manifest,
        SEEDS=seeds,
        OPENAPI=openapi,
    )
    module._metadata_value = lambda model, thinking: {
        "model": model,
        "thinking": thinking,
        "skill": str(module.SKILL),
    }
    module._required_files = lambda: ()
    module._prompt = lambda _run_root, _phase: "base prompt"

    helper._install_execution_skill(module, frozen)

    assert module.SKILL == frozen
    assert module._metadata_value("zai/glm-5.3", "high")["skill"] == str(original)
    assert module.SKILL == frozen
    required = module._required_files()
    assert original / "SKILL.md" in required
    assert frozen / "SKILL.md" in required
    assert helper.SCHEDULE_HANDLER in required
    phase06_prompt = module._prompt(
        tmp_path, SimpleNamespace(phase_id=helper.PHASE06_ID)
    )
    assert "inherited project gap" in phase06_prompt
    assert "Use `status: passed`" in phase06_prompt
    assert "get-schedule --redact-process-inputs" in phase06_prompt
    assert "security_rotation_attestation" in phase06_prompt
    assert module._prompt(tmp_path, SimpleNamespace(phase_id="other")) == "base prompt"


def test_existing_phase06_inherited_gap_is_normalized_without_reexecution(tmp_path):
    helper = _load()
    run_root = _completed_phase06_run(tmp_path, helper)

    record = helper._normalize_existing_phase06_report(run_root)

    assert record is not None
    assert record["phase_status_before"] == "passed_with_gap"
    assert record["phase_status_after"] == "passed"
    assert record["aggregate_project_status"] == "passed_with_gap"
    assert record["required_checks_passed"] == 2
    assert record["platform_calls"] == 0
    assert record["model_calls"] == 0

    phase06 = json.loads(
        (run_root / f"phases/{helper.PHASE06_ID}.json").read_text(encoding="utf-8")
    )
    assert phase06["status"] == "passed"
    assert phase06["gaps"] == []
    assert phase06["inherited_project_gaps"][0]["id"] == "custom-connector-fallback"
    assert phase06["status_scope"]["inherited_from_phase"] == helper.PHASE03_ID

    final = json.loads((run_root / "final-report.json").read_text(encoding="utf-8"))
    assert final["project_status"] == "passed_with_gap"
    assert final["phase_verdicts"][0]["status"] == "passed"
    assert final["remaining_gaps"][0]["id"] == "custom-connector-fallback"

    archive = run_root / helper.NORMALIZATION_RELATIVE / "original-phase06-report.json"
    archived = json.loads(archive.read_text(encoding="utf-8"))
    assert archived["status"] == "passed_with_gap"
    assert helper._normalize_existing_phase06_report(run_root) is None


def test_status_normalization_resumes_after_final_report_was_written(tmp_path):
    helper = _load()
    run_root = _completed_phase06_run(tmp_path, helper)
    recovery_root = run_root / helper.NORMALIZATION_RELATIVE
    final_archive = recovery_root / "original-final-report.json"
    final_archive.parent.mkdir(parents=True)
    original = (run_root / "final-report.json").read_bytes()
    final_archive.write_bytes(original)

    partial = json.loads(original)
    partial, _changes = helper._normalize_phase06_nodes(partial)
    partial["phase06_status_scope"] = {
        "phase_status": "passed",
        "aggregate_project_status": "passed_with_gap",
        "inherited_from_phase": helper.PHASE03_ID,
        "normalization_record": str(recovery_root / "normalization.json"),
    }
    _write(run_root / "final-report.json", partial)

    record = helper._normalize_existing_phase06_report(run_root)

    assert record is not None
    assert record["phase_status_after"] == "passed"
    phase06 = json.loads(
        (run_root / f"phases/{helper.PHASE06_ID}.json").read_text(encoding="utf-8")
    )
    assert phase06["status"] == "passed"
    assert json.loads(final_archive.read_text(encoding="utf-8"))["phase_verdicts"][0][
        "status"
    ] == "passed_with_gap"


def test_phase06_status_normalization_rejects_a_new_local_gap(tmp_path):
    helper = _load()
    run_root = _completed_phase06_run(tmp_path, helper, local_gap=True)

    with pytest.raises(ValueError, match="new or unrecognized local gap"):
        helper._normalize_existing_phase06_report(run_root)

    phase06 = json.loads(
        (run_root / f"phases/{helper.PHASE06_ID}.json").read_text(encoding="utf-8")
    )
    assert phase06["status"] == "passed_with_gap"
    assert not (run_root / helper.NORMALIZATION_RELATIVE).exists()


def test_recorded_token_exposure_requires_separate_rotation(tmp_path):
    helper = _load()
    run_root = tmp_path / "run"
    evidence_path = run_root / helper.EXPOSURE_EVIDENCE_RELATIVES[0]
    _write(
        evidence_path,
        {
            "summary": (
                "A debug print displayed the access token value in this conversation "
                "transcript; the raw file was later redacted."
            )
        },
    )

    with pytest.raises(helper.SecurityRotationRequired, match="redaction does not"):
        helper._security_gate(run_root)


def test_security_gate_accepts_matching_rotation_attestation(tmp_path):
    helper = _load()
    run_root = tmp_path / "run"
    evidence_path = run_root / helper.EXPOSURE_EVIDENCE_RELATIVES[0]
    _write(evidence_path, {"summary": "Transient exposure of the clear token occurred."})
    expected = _rotation_attestation(run_root, helper)

    evidence, attestation = helper._security_gate(run_root)

    assert str(evidence_path) in evidence
    assert attestation == expected


def test_attach_rotation_lineage_to_fresh_phase06_and_final_report(tmp_path):
    helper = _load()
    run_root = tmp_path / "run"
    attestation = _rotation_attestation(run_root, helper)
    phase06 = _phase(helper, helper.PHASE06_ID, "passed")
    _write(run_root / f"phases/{helper.PHASE06_ID}.json", phase06)
    _write(run_root / "final-report.json", {"project_status": "passed_with_gap"})

    helper._attach_rotation_lineage(run_root, attestation)

    phase06 = json.loads(
        (run_root / f"phases/{helper.PHASE06_ID}.json").read_text(encoding="utf-8")
    )
    marker = phase06["security_rotation_attestation"]
    assert marker["path"] == str(run_root / helper.ROTATION_ATTESTATION_RELATIVE)
    assert marker["old_token_revoked"] is True
    final = json.loads((run_root / "final-report.json").read_text(encoding="utf-8"))
    assert final["security_rotation_attestation"] == marker


def test_main_forwards_only_phase06_with_frozen_skill(tmp_path, monkeypatch):
    helper = _load()
    original = _skill(tmp_path / "original")
    frozen = _skill(tmp_path / "frozen")
    calls: list[str] = []
    normalized: list[Path] = []

    module = SimpleNamespace(
        SKILL=original,
        CONTRACT=tmp_path / "contract",
        MANIFEST=tmp_path / "manifest",
        SEEDS=tmp_path / "seeds",
        OPENAPI=tmp_path / "openapi",
    )
    module._metadata_value = lambda model, thinking: {"skill": str(module.SKILL)}
    module._required_files = lambda: ()
    module._prompt = lambda _run_root, _phase: "prompt"
    module.main = lambda argv: calls.extend(argv) or 0
    monkeypatch.setattr(helper, "_load_original", lambda: module)
    monkeypatch.setattr(helper, "_security_gate", lambda _run_root: ([], None))
    monkeypatch.setattr(
        helper,
        "_normalize_existing_phase06_report",
        lambda run_root: normalized.append(run_root) or None,
    )
    run_root = tmp_path / "run"

    code = helper.main(
        [
            "--model",
            "zai/glm-5.3",
            "--thinking",
            "high",
            "--run-root",
            str(run_root),
            "--skill-root",
            str(frozen),
            "--max-hours",
            "1",
            "--confirm",
            helper.CONFIRMATION,
        ]
    )

    assert code == 0
    assert module.SKILL == frozen
    assert normalized == [run_root.resolve()]
    assert calls[calls.index("--phase") + 1] == helper.PHASE06_ID
    assert calls[calls.index("--confirm") + 1] == helper.ORIGINAL_CONFIRMATION
    assert calls[calls.index("--model") + 1] == "zai/glm-5.3"
    assert calls[calls.index("--thinking") + 1] == "high"
