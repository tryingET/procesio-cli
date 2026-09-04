from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
LAUNCHER = ROOT / "scripts" / "start-local-pi-gate5-series-overnight.sh"
UV_ENTRYPOINT = ROOT / "scripts" / "run-local-pi-gate5-overnight.py"
CANONICAL_RUNNER = ROOT / "scripts" / "run-local-pi-gate5-series-unattended.py"


def test_uv_entrypoint_is_pep723_and_delegates_to_one_canonical_runner():
    text = UV_ENTRYPOINT.read_text(encoding="utf-8")
    lines = text.splitlines()

    assert lines[0] == "#!/usr/bin/env -S uv run --script"
    assert "# /// script" in lines[:12]
    assert '# requires-python = ">=3.11"' in lines[:12]
    assert "# dependencies = []" in lines[:12]
    assert "# ///" in lines[:12]
    assert CANONICAL_RUNNER.name in text
    assert "runpy.run_path" in text
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
