from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[2]
LAUNCHER = ROOT / "scripts" / "start-local-pi-gate5-series-overnight.sh"
UV_ENTRYPOINT = ROOT / "scripts" / "run-local-pi-gate5-overnight.py"
CANONICAL_RUNNER = ROOT / "scripts" / "run-local-pi-gate5-series-unattended.py"


def _load_entrypoint():
    spec = importlib.util.spec_from_file_location("gate5_uv_entrypoint", UV_ENTRYPOINT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _status(*, code: str, remaining: int = 9) -> dict:
    return {
        "status": "error",
        "stop_reason": "phase_non_retryable",
        "completed_observations": 351,
        "remaining_observations": remaining,
        "last_result": {
            "interruption": {
                "runner_error": {
                    "code": code,
                    "message": "Pi exited before producing a result.",
                }
            }
        },
    }


def test_uv_entrypoint_is_pep723_and_delegates_to_one_canonical_runner():
    text = UV_ENTRYPOINT.read_text(encoding="utf-8")
    lines = text.splitlines()

    assert lines[0] == "#!/usr/bin/env -S uv run --script"
    assert "# /// script" in lines[:12]
    assert '# requires-python = ">=3.11"' in lines[:12]
    assert "# dependencies = []" in lines[:12]
    assert "# ///" in lines[:12]
    assert CANONICAL_RUNNER.name in text
    assert "subprocess.run" in text
    assert "GATE5_TRANSIENT_RESTARTS" in text
    assert "pi_invocation_failed" in text
    assert "Downloads" not in text


def test_uv_entrypoint_reaches_canonical_help_without_project_python():
    process = subprocess.run(
        ["uv", "run", "--script", str(UV_ENTRYPOINT), "--help"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )

    assert process.returncode == 0, process.stderr
    assert "--run-root" in process.stdout
    assert "--confirm-max-model-calls" in process.stdout
    assert "--max-hours" in process.stdout


def test_only_uncheckpointed_generic_pi_exit_is_process_retryable():
    entrypoint = _load_entrypoint()

    assert entrypoint._transient_pi_exit(2, _status(code="pi_invocation_failed"))
    assert not entrypoint._transient_pi_exit(2, _status(code="model_not_available"))
    assert not entrypoint._transient_pi_exit(2, _status(code="strict_runner_failure"))
    assert not entrypoint._transient_pi_exit(
        2, _status(code="pi_invocation_failed", remaining=0)
    )
    assert not entrypoint._transient_pi_exit(
        75, _status(code="pi_invocation_failed")
    )


def test_transient_pi_exit_repreflights_by_restarting_canonical_runner(
    monkeypatch, tmp_path
):
    entrypoint = _load_entrypoint()
    status_path = tmp_path / "series-status.json"
    calls: list[list[str]] = []
    sleeps: list[float] = []

    def fake_run(argv, **_kwargs):
        calls.append(list(argv))
        if len(calls) == 1:
            status_path.write_text(
                json.dumps(_status(code="pi_invocation_failed")), encoding="utf-8"
            )
            return SimpleNamespace(returncode=2)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(entrypoint.subprocess, "run", fake_run)
    monkeypatch.setattr(entrypoint.time, "sleep", sleeps.append)
    monkeypatch.setenv("GATE5_TRANSIENT_RESTARTS", "3")
    monkeypatch.setenv("GATE5_TRANSIENT_RETRY_SECONDS", "1")

    code = entrypoint.main(
        [
            "--run-root",
            str(tmp_path),
            "--confirm-max-model-calls",
            "20",
        ]
    )

    assert code == 0
    assert len(calls) == 2
    assert sleeps == [1]
    assert calls[0][0] == sys.executable
    assert calls[0][1] == str(CANONICAL_RUNNER)
    assert calls[0][2:] == calls[1][2:]


def test_nontransient_runner_error_is_not_restarted(monkeypatch, tmp_path):
    entrypoint = _load_entrypoint()
    status_path = tmp_path / "series-status.json"
    status_path.write_text(
        json.dumps(_status(code="model_not_available")), encoding="utf-8"
    )
    calls = 0

    def fake_run(_argv, **_kwargs):
        nonlocal calls
        calls += 1
        return SimpleNamespace(returncode=2)

    monkeypatch.setattr(entrypoint.subprocess, "run", fake_run)
    monkeypatch.setattr(
        entrypoint.time,
        "sleep",
        lambda _seconds: (_ for _ in ()).throw(AssertionError("unexpected retry")),
    )

    code = entrypoint.main(
        [
            "--run-root",
            str(tmp_path),
            "--confirm-max-model-calls",
            "20",
        ]
    )

    assert code == 2
    assert calls == 1


def test_launcher_is_foreground_bounded_resumable_and_uses_uv_script_mode():
    text = LAUNCHER.read_text(encoding="utf-8")

    assert "uv run --script" in text
    assert UV_ENTRYPOINT.name in text
    assert "uv run python" not in text
    assert "GATE5_RUN_ROOT" in text
    assert "gate5-series-v4-overnight" in text
    assert "GATE5_MAX_HOURS:-8" in text
    assert "GATE5_MAX_MODEL_CALLS:-900" in text
    assert "--confirm-max-model-calls \"$MAX_CALLS\"" in text
    assert "nohup" not in text
    assert "exec" in text


def test_launcher_pins_model_and_thinking_and_prevents_sleep_when_available():
    text = LAUNCHER.read_text(encoding="utf-8")

    assert "PI_EVAL_MODEL must contain an exact provider/model ID" in text
    assert "PI_EVAL_THINKING:-medium" in text
    assert 'PI_EVAL_MODEL="$MODEL"' in text
    assert 'PI_EVAL_THINKING="$THINKING"' in text
    assert "systemd-inhibit" in text
    assert "--what=sleep:idle" in text
