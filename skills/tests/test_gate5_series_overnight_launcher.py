from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
LAUNCHER = ROOT / "scripts" / "start-local-pi-gate5-series-overnight.sh"


def test_launcher_is_foreground_bounded_and_resumable():
    text = LAUNCHER.read_text(encoding="utf-8")

    assert "run-local-pi-gate5-series-unattended.py" in text
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
