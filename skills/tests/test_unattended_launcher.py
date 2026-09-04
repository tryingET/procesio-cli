from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
LAUNCHER = ROOT / "scripts" / "start-local-pi-gate5-aa-unattended.sh"


def test_launcher_uses_direct_nohup_without_login_shell():
    text = LAUNCHER.read_text(encoding="utf-8")

    assert "nohup" in text
    assert "run-local-pi-gate5-aa-unattended.py" in text
    assert "bash -lc" not in text
    assert "</dev/null" in text
    assert "PYTHONUNBUFFERED=1" in text


def test_launcher_preserves_checkpoint_and_handles_stale_process_state():
    text = LAUNCHER.read_text(encoding="utf-8")

    assert "run-metadata.json" in text
    assert "kill -0" in text
    assert "unattended-status.previous.json" in text
    assert "rm -f \"$STATUS\"" in text
    assert "rm -f \"$PID_FILE\"" in text


def test_launcher_waits_for_immediate_detached_startup_failures():
    text = LAUNCHER.read_text(encoding="utf-8")

    assert "ATTEMPT <= 10" in text
    assert "exited during startup" in text
    assert '"status": "complete"' in text


def test_launcher_has_bounded_unattended_defaults():
    text = LAUNCHER.read_text(encoding="utf-8")

    assert 'GATE5_MAX_HOURS:-5' in text
    assert 'GATE5_BATCH_OBSERVATIONS:-8' in text
    assert 'GATE5_MAX_MODEL_CALLS:-120' in text
    assert 'GATE5_MAX_BACKOFF_SECONDS:-1800' in text
    assert '--confirm-max-model-calls "$MAX_MODEL_CALLS"' in text


def test_launcher_does_not_start_ab():
    text = LAUNCHER.read_text(encoding="utf-8")

    assert "gate5-aa" in text
    assert "gate5-ab" not in text
