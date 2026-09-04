from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "run-local-pi-gate5-overnight.py"


def _load_entrypoint():
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        spec = importlib.util.spec_from_file_location(
            "run_local_pi_gate5_overnight", SCRIPT
        )
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.pop(0)


def test_entrypoint_is_a_self_contained_uv_script():
    text = SCRIPT.read_text(encoding="utf-8")
    lines = text.splitlines()

    assert lines[0] == "#!/usr/bin/env -S uv run --script"
    assert "# /// script" in lines[:12]
    assert '# requires-python = ">=3.11"' in lines[:12]
    assert "# dependencies = []" in lines[:12]
    assert "# ///" in lines[:12]
    assert "Downloads" not in text


def test_defaults_target_the_checked_out_repo_and_bounded_overnight_run():
    runner = _load_entrypoint()
    args = runner.build_parser().parse_args(
        ["--confirm-max-model-calls", "760"]
    )

    assert args.repo == ROOT
    assert args.max_hours == 8
    assert args.batch_observations == 8
    assert args.confirm_max_model_calls == 760
    assert args.model == "opencode-go/muse-spark-1.3-contributor"
    assert args.thinking == "medium"


def test_detached_worker_is_relaunched_through_uv_script_mode(monkeypatch, tmp_path):
    runner = _load_entrypoint()
    monkeypatch.setattr(runner.shutil, "which", lambda name: "/usr/bin/uv" if name == "uv" else None)
    args = runner.build_parser().parse_args(
        ["--confirm-max-model-calls", "760"]
    )

    command = runner.child_command(args, tmp_path / "run")

    assert command[:3] == ["/usr/bin/uv", "run", "--script"]
    assert command[3] == str(SCRIPT.resolve())
    assert "--detach" not in command


def test_fixed_phase_order_and_frozen_two_skill_baseline():
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        from _gate5_overnight import common
    finally:
        sys.path.pop(0)

    assert common.BASELINE_REF == "da12de643c8a2355d019f40515766abf80a819df"
    assert common.SUITE_VERSION == 4
    assert common.RUBRIC_CONTRACT == "fixed-jury-rubric-v2"
    assert common.PHASES == (
        ("aa", "aa", 20260902),
        ("ab-round-1", "ab", 20260903),
        ("ab-round-2", "ab", 20260904),
    )
    assert common.EXPECTED_CANDIDATE == {
        "agent-skill-engineer",
        "procesio-cli",
        "procesio-cli-maintainer",
        "procesio-platform-advisor",
        "sql-server-optimizer",
    }
    assert common.EXPECTED_BASELINE == {
        "procesio-expert",
        "sql-server-optimizer",
    }
