from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "run-procesio-control-tower.py"


def _load():
    spec = importlib.util.spec_from_file_location("run_procesio_control_tower", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_launcher_is_uv_inline_script_and_locks_requested_model():
    text = SCRIPT.read_text(encoding="utf-8")
    assert text.startswith("#!/usr/bin/env -S uv run --script")
    assert '# requires-python = ">=3.11"' in text
    module = _load()
    assert module.DEFAULT_MODEL == "zai/glm-5.3"
    assert module.DEFAULT_THINKING == "high"
    assert module.CONFIRMATION == "BUILD_PROCESIO_CONTROL_TOWER_V1"
    assert len(module.PHASES) == 6


def test_dry_run_makes_no_model_or_platform_call(tmp_path, capsys):
    module = _load()
    code = module.main(["--dry-run", "--run-root", str(tmp_path / "run")])
    assert code == 0
    result = json.loads(capsys.readouterr().out)
    assert result["dry_run"] is True
    assert result["model"] == "zai/glm-5.3"
    assert result["thinking"] == "high"
    assert result["platform_calls"] == 0
    assert result["model_calls"] == 0
    assert result["automatic_phase_retries"] == 0
    assert len(result["phases"]) == 6


def test_mutating_run_requires_exact_confirmation(tmp_path, capsys):
    module = _load()
    code = module.main(["--run-root", str(tmp_path / "run")])
    assert code == 2
    result = json.loads(capsys.readouterr().out)
    assert result["error"]["code"] == "confirmation_required"
    assert module.CONFIRMATION in result["error"]["message"]


def test_model_inventory_requires_provider_and_model_on_same_line(monkeypatch):
    module = _load()

    def fake_run(*_args, **_kwargs):
        return SimpleNamespace(
            returncode=0,
            stdout=(
                "provider               model\n"
                "zai                    glm-5.3\n"
                "opencode-go            glm-5.3\n"
            ),
            stderr="",
        )

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    ready, matches, error = module._model_inventory("pi", "zai/glm-5.3")
    assert ready is True
    assert matches == ["zai                    glm-5.3"]
    assert error == ""

    ready, related, error = module._model_inventory("pi", "missing/glm-5.3")
    assert ready is False
    assert related
    assert "exact model" in error


def test_phase_report_fails_closed_on_unknown_or_unsafe_pass(tmp_path):
    module = _load()
    phase = module.PHASES[1]
    path = tmp_path / "phase.json"
    base = {
        "schema_version": 1,
        "project_id": module.PROJECT_ID,
        "phase": phase.phase_id,
        "status": "passed",
        "summary": "ok",
        "resources": [],
        "executions": [],
        "checks": [],
        "gaps": [],
        "unknown_outcomes": [],
        "next_phase_safe": True,
    }
    path.write_text(json.dumps(base), encoding="utf-8")
    assert module._validate_phase_report(path, phase)["status"] == "passed"

    unsafe = {**base, "next_phase_safe": False}
    path.write_text(json.dumps(unsafe), encoding="utf-8")
    with pytest.raises(ValueError, match="next_phase_safe"):
        module._validate_phase_report(path, phase)

    unknown = {**base, "unknown_outcomes": [{"operation": "create"}]}
    path.write_text(json.dumps(unknown), encoding="utf-8")
    with pytest.raises(ValueError, match="unknown outcomes"):
        module._validate_phase_report(path, phase)


def test_only_connector_phase_may_pass_with_gap(tmp_path):
    module = _load()
    report = {
        "schema_version": 1,
        "project_id": module.PROJECT_ID,
        "status": "passed_with_gap",
        "summary": "fallback verified",
        "resources": [],
        "executions": [],
        "checks": [],
        "gaps": ["connector unavailable"],
        "unknown_outcomes": [],
        "next_phase_safe": True,
    }
    connector = module.PHASES[2]
    connector_path = tmp_path / "connector.json"
    connector_path.write_text(
        json.dumps({**report, "phase": connector.phase_id}), encoding="utf-8"
    )
    assert module._validate_phase_report(connector_path, connector)["status"] == "passed_with_gap"

    other = module.PHASES[1]
    other_path = tmp_path / "other.json"
    other_path.write_text(json.dumps({**report, "phase": other.phase_id}), encoding="utf-8")
    with pytest.raises(ValueError, match="only phase 03"):
        module._validate_phase_report(other_path, other)


def test_project_contract_is_ambitious_bounded_and_not_a_throwaway():
    project_dir = ROOT / "examples" / "procesio" / "control-tower"
    manifest = json.loads((project_dir / "control-tower.project.json").read_text())
    assert manifest["project_id"] == "procesio-control-tower-v1"
    assert manifest["existing_dependency"]["process_id"] == "0528c553-8e17-4185-84cb-11068db503d8"
    assert len(manifest["retained_resources"]["processes"]) == 4
    assert manifest["retained_resources"]["webhooks_final"] == []
    assert manifest["resource_caps"]["temporary_webhooks"] == 1
    assert manifest["resource_caps"]["representative_process_executions_during_build"] <= 20
    assert manifest["security_and_cost"]["automatic_retry_after_unknown_write"] is False
    assert manifest["security_and_cost"]["schedule"]["monthly_platform_runtime_guard_minutes"] <= 120

    required = "\n".join(manifest["required_capability_coverage"]).casefold()
    for feature in (
        "data model",
        "data-store",
        "call subprocess",
        "decisional",
        "for each",
        "custom response",
        "connector",
        "document",
        "form",
        "webhook",
        "schedule",
        "transport export",
    ):
        assert feature in required

    contract = (project_dir / "control-tower.field-contract.md").read_text(encoding="utf-8")
    assert "not a disposable demo" in contract
    assert "Never blind-retry" in contract
    assert "zero exact-title webhooks remain" in contract
    assert "founder" in contract.casefold()
