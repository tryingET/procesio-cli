from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "run-procesio-control-tower-token-rotation.py"


def _load():
    spec = importlib.util.spec_from_file_location(
        "run_procesio_control_tower_token_rotation", SCRIPT
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _stage_report(module, metadata: dict) -> dict:
    return {
        "schema_version": 1,
        "project_id": module.PROJECT_ID,
        "remediation_id": module.REMEDIATION_ID,
        "stage": module.STAGE_ID,
        "status": "passed",
        "summary": "Old token rejected, replacement accepted, no clear token retained.",
        "checks": [
            {"id": check_id, "passed": True, "evidence": f"proof:{check_id}"}
            for check_id in module.REQUIRED_CHECKS
        ],
        "budget_usage": dict(module.BUDGET),
        "token_rotation": {
            "old_sha256": metadata["old_token_sha256"],
            "new_sha256": metadata["new_token_sha256"],
            "evidence_key": metadata["evidence_key"],
            "ingest_process_id": "d46af04c-7cc7-4777-ad0e-dd049ad58a8b",
            "schedule_id": "schedule-1",
            "old_token_instance_id": "old-instance",
            "new_token_instance_ids": ["new-instance", "normalizer-child"],
            "ledger_row_identity": metadata["evidence_key"],
        },
        "resources": [],
        "executions": [],
        "gaps": [],
        "unknown_outcomes": [],
        "next_stage_safe": True,
    }


def _run_state(tmp_path: Path, module):
    run_root = tmp_path / "run"
    rotation = module._rotation_root(run_root)
    rotation.mkdir(parents=True)
    old = b"old-secret-token-material-123456"
    new = b"new-secret-token-material-654321"
    token_path = module._token_path(run_root)
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_bytes(old + b"\n")
    new_path = module._new_token_path(run_root)
    new_path.write_bytes(new + b"\n")
    if os.name != "nt":
        os.chmod(token_path, 0o600)
        os.chmod(new_path, 0o600)

    phase05 = {
        "schema_version": 1,
        "project_id": module.PROJECT_ID,
        "phase": module.PHASE05_ID,
        "status": "passed",
        "summary": "functional remediation passed",
        "checks": [],
        "resources": [],
        "executions": [],
        "gaps": [],
        "unknown_outcomes": [],
        "next_phase_safe": True,
        "remediation": {"remediation_id": module.PHASE05_REMEDIATION_ID},
    }
    phase05_path = module._phase_path(run_root, module.PHASE05_ID)
    _write_json(phase05_path, phase05)
    metadata = {
        "schema_version": 1,
        "project_id": module.PROJECT_ID,
        "remediation_id": module.REMEDIATION_ID,
        "stage": module.STAGE_ID,
        "old_token_sha256": module._sha256_bytes(old),
        "new_token_sha256": module._sha256_bytes(new),
        "evidence_key": "control-tower:token-rotation:test",
        "phase05_sha256": module._sha256(phase05_path),
    }
    report = _stage_report(module, metadata)
    _write_json(module._stage_path(run_root), report)

    phase06 = {
        "schema_version": 1,
        "project_id": module.PROJECT_ID,
        "phase": module.PHASE06_ID,
        "status": "passed_with_gap",
        "unknown_outcomes": [],
        "next_phase_safe": True,
    }
    _write_json(module._phase_path(run_root, module.PHASE06_ID), phase06)
    _write_json(run_root / "final-report.json", {"status": "passed_with_gap"})
    _write_json(run_root / "deployment.json", {"schema_version": 1})
    _write_json(run_root / "coordinator-status.json", {"state": "error"})
    export = run_root / "export"
    export.mkdir()
    (export / "control-tower-retained.procesio").write_bytes(b"old-export")
    (export / "evidence-ledger.csv").write_text("Evidence Key\nkey\n", encoding="utf-8")
    return run_root, metadata, report, old, new


def test_rotation_launcher_is_uv_script_and_has_no_automatic_retry():
    text = SCRIPT.read_text(encoding="utf-8")
    assert text.startswith("#!/usr/bin/env -S uv run --script")
    assert '# requires-python = ">=3.11"' in text
    assert "automatic_stage_retries" in text
    assert "for attempt" not in text
    assert "while attempt" not in text


def test_dry_run_does_not_generate_token(tmp_path, monkeypatch, capsys):
    module = _load()
    manifest = tmp_path / "manifest.json"
    _write_json(manifest, {"project_id": module.PROJECT_ID})
    files = []
    for name in ("contract", "original", "phase05", "skill", "handler", "security"):
        path = tmp_path / name
        path.write_text("x", encoding="utf-8")
        files.append(path)
    monkeypatch.setattr(module, "MANIFEST", manifest)
    monkeypatch.setattr(module, "_required_files", lambda: tuple(files))
    run_root = tmp_path / "run"

    code = module.main(["--run-root", str(run_root), "--dry-run"])

    assert code == 0
    result = json.loads(capsys.readouterr().out)
    assert result["dry_run"] is True
    assert result["required_checks"] == list(module.REQUIRED_CHECKS)
    assert result["budget"] == module.BUDGET
    assert not module._rotation_root(run_root).exists()


def test_stage_report_requires_fixed_checks_and_exact_passing_budget(tmp_path):
    module = _load()
    metadata = {
        "old_token_sha256": "a" * 64,
        "new_token_sha256": "b" * 64,
        "evidence_key": "rotation-key",
    }
    report = _stage_report(module, metadata)
    path = tmp_path / "stage.json"
    _write_json(path, report)

    assert module._validate_stage_report(path, metadata)["status"] == "passed"

    report["checks"][0], report["checks"][1] = report["checks"][1], report["checks"][0]
    _write_json(path, report)
    with pytest.raises(ValueError, match="ids/order"):
        module._validate_stage_report(path, metadata)

    report = _stage_report(module, metadata)
    report["budget_usage"]["process_instances"] = 2
    _write_json(path, report)
    with pytest.raises(ValueError, match="passing budget must equal"):
        module._validate_stage_report(path, metadata)


def test_host_scan_rejects_clear_token_outside_protected_files(tmp_path):
    module = _load()
    run_root, metadata, _report, old, _new = _run_state(tmp_path, module)
    leaked = run_root / "leaked.log"
    leaked.write_bytes(b"prefix " + old + b" suffix")

    with pytest.raises(ValueError, match="clear token found"):
        module._host_scan_before_replace(run_root, metadata)

    assert module._sha256_bytes(module._token_value(module._token_path(run_root))) == metadata[
        "old_token_sha256"
    ]


def test_host_finalization_rotates_token_and_invalidates_phase06(tmp_path):
    module = _load()
    run_root, metadata, report, _old, new = _run_state(tmp_path, module)

    attestation = module._finalize(run_root, metadata=metadata, report=report)

    assert attestation["status"] == "passed"
    assert attestation["old_token_revoked"] is True
    assert attestation["replacement_token_proven"] is True
    assert attestation["redaction_erased_incident"] is False
    assert attestation["phase06_artifacts_invalidated"] is True
    assert module._token_value(module._token_path(run_root)) == new
    assert not module._new_token_path(run_root).exists()
    assert not module._phase_path(run_root, module.PHASE06_ID).exists()
    assert not (run_root / "final-report.json").exists()
    assert not (run_root / "deployment.json").exists()
    assert not (run_root / "export").exists()

    phase05 = json.loads(
        module._phase_path(run_root, module.PHASE05_ID).read_text(encoding="utf-8")
    )
    security = phase05["security_remediation"]
    assert security["remediation_id"] == module.REMEDIATION_ID
    assert security["redaction_erased_incident"] is False
    assert security["old_token_revoked"] is True
    assert security["new_token_sha256"] == metadata["new_token_sha256"]
    assert (
        module._rotation_root(run_root)
        / "archive"
        / "phase05-pre-security-rotation.json"
    ).is_file()
    assert (
        module._rotation_root(run_root)
        / "archive"
        / "pre-rotation-phase06"
        / "export"
        / "control-tower-retained.procesio"
    ).is_file()

    # Finalization is idempotent after the attestation is written.
    assert module._finalize(run_root, metadata=metadata, report=report) == attestation


def test_finalization_resumes_after_token_file_was_already_replaced(tmp_path):
    module = _load()
    run_root, metadata, report, _old, new = _run_state(tmp_path, module)
    module._host_scan_before_replace(run_root, metadata)
    module._replace_token_file(run_root, metadata, new)

    attestation = module._finalize(run_root, metadata=metadata, report=report)

    assert attestation["status"] == "passed"
    assert module._token_value(module._token_path(run_root)) == new
    assert not module._new_token_path(run_root).exists()
