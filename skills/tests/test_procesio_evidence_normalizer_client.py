from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "run-procesio-evidence-normalizer.py"
DEPLOYMENT = ROOT / "examples" / "procesio" / "evidence-status-normalizer.deployment.json"


def _load():
    spec = importlib.util.spec_from_file_location("evidence_normalizer_client", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _deployment() -> dict:
    return {
        "profile": "pure-awesomeness",
        "environment": "Internal-PROD",
        "workspace_id": "dc28053d-f701-4880-99c2-7d973899d135",
        "process_id": "0528c553-8e17-4185-84cb-11068db503d8",
        "title": "CLI Utility 01 - Evidence Status Normalizer",
    }


def test_script_is_pep723_and_deployment_is_non_secret():
    lines = SCRIPT.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "#!/usr/bin/env -S uv run --script"
    assert "# /// script" in lines[:10]
    assert '# requires-python = ">=3.11"' in lines[:10]
    assert "# dependencies = []" in lines[:10]

    deployment = json.loads(DEPLOYMENT.read_text(encoding="utf-8"))
    assert deployment["process_id"] == "0528c553-8e17-4185-84cb-11068db503d8"
    assert deployment["profile"] == "pure-awesomeness"
    text = DEPLOYMENT.read_text(encoding="utf-8").casefold()
    assert "key handle" not in text
    assert "password" not in text
    assert "api key" not in text


def test_success_runs_once_then_reads_exact_instance_output():
    module = _load()
    calls: list[list[str]] = []

    def runner(argv, _timeout):
        calls.append(list(argv))
        if argv[0] == "check-auth":
            return module.Call(0, {"authenticated": True})
        if argv[0] == "run-process":
            return module.Call(0, {"result": {"instanceId": "iid-1", "status": 50}})
        if argv[0] == "get-instance-output":
            return module.Call(
                0,
                {
                    "result": {
                        "instance": {
                            "status": 50,
                            "variable": [
                                {
                                    "name": "normalized",
                                    "value": json.dumps(
                                        {
                                            "decision": "ACCEPT_EVIDENCE",
                                            "complete": True,
                                        }
                                    ),
                                },
                                {"name": "script_error", "value": None},
                            ],
                        }
                    }
                },
            )
        raise AssertionError(argv)

    code, result = module.run_once(
        {"status": "complete"},
        _deployment(),
        runner=runner,
    )

    assert code == 0
    assert result["ok"] is True
    assert result["instance_id"] == "iid-1"
    assert result["normalized"]["decision"] == "ACCEPT_EVIDENCE"
    assert result["executions_this_invocation"] == 1
    assert result["retry_performed"] is False
    assert [call[0] for call in calls] == [
        "check-auth",
        "run-process",
        "get-instance-output",
    ]
    assert sum(call[0] == "run-process" for call in calls) == 1


def test_timeout_is_unknown_and_never_retried():
    module = _load()
    calls: list[list[str]] = []

    def runner(argv, _timeout):
        calls.append(list(argv))
        if argv[0] == "check-auth":
            return module.Call(0, {"authenticated": True})
        return module.Call(124, None, timed_out=True)

    code, result = module.run_once(
        {"status": "paused"},
        _deployment(),
        runner=runner,
    )

    assert code == 1
    assert result["error"]["code"] == "unknown_run_outcome"
    assert result["error"]["details"]["retry_performed"] is False
    assert [call[0] for call in calls] == ["check-auth", "run-process"]


def test_known_instance_output_failure_does_not_launch_second_run():
    module = _load()
    calls: list[list[str]] = []

    def runner(argv, _timeout):
        calls.append(list(argv))
        if argv[0] == "check-auth":
            return module.Call(0, {"authenticated": True})
        if argv[0] == "run-process":
            return module.Call(0, {"result": {"instanceId": "iid-2", "status": 50}})
        return module.Call(
            1,
            {"error": {"code": "permission_denied", "message": "no", "details": {}}},
        )

    code, result = module.run_once(
        {"status": "complete"},
        _deployment(),
        runner=runner,
    )

    assert code == 1
    assert result["error"]["code"] == "instance_output_unavailable"
    assert result["error"]["details"]["instance_id"] == "iid-2"
    assert sum(call[0] == "run-process" for call in calls) == 1


def test_auth_failure_stops_before_run():
    module = _load()
    calls: list[list[str]] = []

    def runner(argv, _timeout):
        calls.append(list(argv))
        return module.Call(0, {"authenticated": False, "status": 403})

    code, result = module.run_once(
        {"status": "complete"},
        _deployment(),
        runner=runner,
    )

    assert code == 1
    assert result["error"]["code"] == "authentication_failed"
    assert [call[0] for call in calls] == ["check-auth"]


def test_dry_run_is_local_and_declares_zero_retries(monkeypatch, capsys):
    module = _load()

    monkeypatch.setattr(
        module,
        "run_once",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("dry-run must not call PROCESIO")
        ),
    )
    code = module.main(
        [
            "--deployment",
            str(DEPLOYMENT),
            "--json",
            '{"status":"paused","remaining_observations":9}',
            "--dry-run",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    assert payload["dry_run"] is True
    assert payload["automatic_retries"] == 0
    assert payload["calls"] == [
        "check-auth",
        "run-process once",
        "get-instance-output",
    ]
    assert payload["payload"]["status"]["remaining_observations"] == 9
