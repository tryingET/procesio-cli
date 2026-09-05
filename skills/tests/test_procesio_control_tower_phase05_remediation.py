from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "run-procesio-control-tower-phase05-remediation.py"


def _load():
    spec = importlib.util.spec_from_file_location(
        "run_procesio_control_tower_phase05_remediation", SCRIPT
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _phase05_report(module) -> dict:
    return {
        "schema_version": 1,
        "project_id": module.PROJECT_ID,
        "phase": module.PHASE05_ID,
        "status": "passed_with_gap",
        "summary": "substantial work, two acceptance gaps",
        "resources": [],
        "executions": [],
        "checks": [],
        "gaps": [
            {"id": "form-sync-result-rendering"},
            {"id": "webhook-field-mapping"},
        ],
        "unknown_outcomes": [],
        "next_phase_safe": True,
    }


def _stage_report(module, stage, *, budget=None, status="passed") -> dict:
    return {
        "schema_version": 1,
        "project_id": module.PROJECT_ID,
        "remediation_id": module.REMEDIATION_ID,
        "stage": stage.stage_id,
        "status": status,
        "summary": f"{stage.stage_id} complete",
        "resources": [],
        "executions": [],
        "checks": [
            {"id": check_id, "passed": True, "evidence": "direct proof"}
            for check_id in stage.required_checks
        ],
        "budget_usage": budget
        or {"form_submissions": 0, "webhook_launches": 0, "process_instances": 0},
        "gaps": [],
        "unknown_outcomes": [],
        "next_stage_safe": True,
    }


def test_launcher_is_uv_script_and_locks_exact_model_and_budget():
    text = SCRIPT.read_text(encoding="utf-8")
    assert text.startswith("#!/usr/bin/env -S uv run --script")
    assert '# requires-python = ">=3.11"' in text
    module = _load()
    assert module.DEFAULT_MODEL == "zai/glm-5.3"
    assert module.DEFAULT_THINKING == "high"
    assert module.CONFIRMATION == "REMEDIATE_AND_FINISH_PROCESIO_CONTROL_TOWER_V1"
    assert len(module.STAGES) == 3
    assert module.TOTAL_BUDGET == {
        "form_submissions": 1,
        "webhook_launches": 1,
        "process_instances": 5,
    }
    assert module.STAGES[0].budget_limits["process_instances"] == 2
    assert module.STAGES[1].budget_limits["process_instances"] == 3


def test_dry_run_makes_no_model_or_platform_calls(tmp_path, capsys):
    module = _load()
    code = module.main(["--dry-run", "--run-root", str(tmp_path / "run")])
    assert code == 0
    result = json.loads(capsys.readouterr().out)
    assert result["dry_run"] is True
    assert result["model"] == "zai/glm-5.3"
    assert result["thinking"] == "high"
    assert result["platform_calls"] == 0
    assert result["model_calls"] == 0
    assert result["automatic_stage_retries"] == 0
    assert result["phase06_after_promotion"] is True
    assert result["total_budget"]["process_instances"] == 5


def test_mutating_run_requires_exact_confirmation(tmp_path, capsys):
    module = _load()
    code = module.main(["--run-root", str(tmp_path / "run")])
    assert code == 2
    result = json.loads(capsys.readouterr().out)
    assert result["error"]["code"] == "confirmation_required"
    assert module.CONFIRMATION in result["error"]["message"]


def test_phase05_state_requires_the_two_observed_gaps(tmp_path):
    module = _load()
    phase_path = tmp_path / "phases" / f"{module.PHASE05_ID}.json"
    phase_path.parent.mkdir(parents=True)
    phase_path.write_text(json.dumps(_phase05_report(module)), encoding="utf-8")
    state, report = module._phase05_state(tmp_path)
    assert state == "unresolved"
    assert report["status"] == "passed_with_gap"

    bad = _phase05_report(module)
    bad["gaps"] = [{"id": "some-other-gap"}]
    phase_path.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(ValueError, match="expected gap"):
        module._phase05_state(tmp_path)


def test_stage_pass_uses_fixed_check_ids_order_and_rejects_gap(tmp_path):
    module = _load()
    stage = module.STAGES[0]
    path = tmp_path / "stage.json"
    report = _stage_report(
        module,
        stage,
        budget={"form_submissions": 1, "webhook_launches": 0, "process_instances": 2},
    )
    path.write_text(json.dumps(report), encoding="utf-8")
    assert module._validate_stage_report(path, stage)["status"] == "passed"

    reordered = dict(report)
    reordered["checks"] = list(reversed(report["checks"]))
    path.write_text(json.dumps(reordered), encoding="utf-8")
    with pytest.raises(ValueError, match="exactly match"):
        module._validate_stage_report(path, stage)

    gapped = dict(report)
    gapped["status"] = "passed_with_gap"
    path.write_text(json.dumps(gapped), encoding="utf-8")
    with pytest.raises(ValueError, match="passed_with_gap is forbidden"):
        module._validate_stage_report(path, stage)


def test_stage_pass_rejects_unknown_outcome_and_budget_overrun(tmp_path):
    module = _load()
    stage = module.STAGES[1]
    path = tmp_path / "stage.json"
    report = _stage_report(
        module,
        stage,
        budget={"form_submissions": 0, "webhook_launches": 1, "process_instances": 3},
    )
    report["unknown_outcomes"] = [{"operation": "webhook launch"}]
    path.write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(ValueError, match="unknown outcomes"):
        module._validate_stage_report(path, stage)

    report["unknown_outcomes"] = []
    report["budget_usage"]["webhook_launches"] = 2
    path.write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(ValueError, match="exceeds stage limit"):
        module._validate_stage_report(path, stage)


def test_promotion_archives_original_and_resolves_both_gaps(tmp_path):
    module = _load()
    phase_path = tmp_path / "phases" / f"{module.PHASE05_ID}.json"
    phase_path.parent.mkdir(parents=True)
    original = _phase05_report(module)
    phase_path.write_text(json.dumps(original, indent=2), encoding="utf-8")
    metadata = {
        "original_phase05_sha256": module._sha256(phase_path),
    }
    reports = [
        _stage_report(
            module,
            module.STAGES[0],
            budget={"form_submissions": 1, "webhook_launches": 0, "process_instances": 2},
        ),
        _stage_report(
            module,
            module.STAGES[1],
            budget={"form_submissions": 0, "webhook_launches": 1, "process_instances": 3},
        ),
        _stage_report(module, module.STAGES[2]),
    ]

    promoted = module._promote_phase05(tmp_path, metadata=metadata, reports=reports)
    assert promoted["status"] == "passed"
    assert promoted["gaps"] == []
    assert len(promoted["resolved_gaps"]) == 2
    assert promoted["next_phase_safe"] is True
    assert promoted["remediation"]["remediation_id"] == module.REMEDIATION_ID
    assert promoted["remediation"]["budget_exception"]["additional_usage"] == {
        "form_submissions": 1,
        "webhook_launches": 1,
        "process_instances": 5,
    }
    archive = (
        tmp_path
        / "phases"
        / "archive"
        / f"{module.PHASE05_ID}.pre-remediation.json"
    )
    assert json.loads(archive.read_text(encoding="utf-8"))["status"] == "passed_with_gap"
    assert json.loads(phase_path.read_text(encoding="utf-8"))["status"] == "passed"


def test_aggregate_budget_fails_closed():
    module = _load()
    reports = [
        _stage_report(
            module,
            module.STAGES[0],
            budget={"form_submissions": 1, "webhook_launches": 0, "process_instances": 3},
        ),
        _stage_report(
            module,
            module.STAGES[1],
            budget={"form_submissions": 0, "webhook_launches": 1, "process_instances": 3},
        ),
        _stage_report(module, module.STAGES[2]),
    ]
    with pytest.raises(ValueError, match="aggregate remediation budget"):
        module._aggregate_budget(reports)
