from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "run-local-pi-gate5-series-unattended.py"
SPEC = importlib.util.spec_from_file_location("gate5_series_unattended", SCRIPT)
assert SPEC and SPEC.loader
SERIES = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = SERIES
SPEC.loader.exec_module(SERIES)


def _fake_run(tmp_path: Path, *, per_phase: int = 2) -> tuple[Path, dict]:
    for relative in ("candidate", "control", "baseline", "runtime"):
        (tmp_path / relative).mkdir()
    (tmp_path / "candidate" / "evals.json").write_text("{}", encoding="utf-8")
    (tmp_path / "candidate" / "thresholds.json").write_text("{}", encoding="utf-8")
    metadata = {
        "suite_version": 3,
        "rubric_contract": "fixed-jury-rubric-v2",
        "model": "provider/model",
        "provider": None,
        "thinking": "medium",
        "candidate_commit": "candidate",
        "baseline_commit": "baseline",
        "observations_per_phase": per_phase,
        "phase_order": SERIES._phase_specs(),
        "paths": {
            "candidate": "candidate",
            "control": "control",
            "baseline": "baseline",
            "evals": "candidate/evals.json",
            "thresholds": "candidate/thresholds.json",
            "runtime": "runtime",
        },
    }
    return tmp_path, metadata


def _complete_phase(
    run_root: Path,
    phase_id: str,
    *,
    observations: int,
    passed: bool,
) -> dict:
    directory = run_root / "phases" / phase_id
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "runs.jsonl").open("w", encoding="utf-8") as stream:
        for index in range(observations):
            stream.write(json.dumps({"observation": index}) + "\n")
    report = {
        "mode": "aa" if phase_id == "aa" else "ab",
        "candidate_fingerprint": "candidate-fingerprint",
        "baseline_fingerprint": "baseline-fingerprint",
        "gate": {"passed": passed, "reasons": [] if passed else ["failed"]},
    }
    (directory / "report.json").write_text(json.dumps(report), encoding="utf-8")
    return report


def _ready_preflight(**_kwargs):
    return 0, {"ready": True, "marker_seen": True}


def test_phase_order_is_fixed_aa_then_two_ab_rounds():
    assert SERIES._phase_specs() == [
        {"id": "aa", "mode": "aa", "seed": 20260902},
        {"id": "ab-round-1", "mode": "ab", "seed": 20260903},
        {"id": "ab-round-2", "mode": "ab", "seed": 20260904},
    ]


def test_failed_aa_blocks_all_ab_calls(tmp_path):
    run_root, metadata = _fake_run(tmp_path)
    invoked: list[str] = []

    def batch(**kwargs):
        phase = kwargs["phase"]
        invoked.append(phase["id"])
        report = _complete_phase(
            run_root,
            phase["id"],
            observations=2,
            passed=False,
        )
        return 5, report

    code, status = SERIES.run_series(
        run_root=run_root,
        metadata=metadata,
        max_hours=1,
        batch_observations=2,
        initial_backoff_seconds=1,
        max_backoff_seconds=2,
        between_batches_seconds=0,
        preflight_timeout=1,
        observation_timeout=1,
        max_model_calls=20,
        preflight_fn=_ready_preflight,
        batch_fn=batch,
        sleep_fn=lambda _seconds: None,
    )

    assert code == 5
    assert invoked == ["aa"]
    assert status["status"] == "blocked"
    assert status["stop_reason"] == "aa_noise_gate_failed"
    assert status["gate5_evidence"] is False


def test_passing_aa_and_two_ab_rounds_produce_series_evidence(monkeypatch, tmp_path):
    run_root, metadata = _fake_run(tmp_path)
    invoked: list[str] = []

    def batch(**kwargs):
        phase = kwargs["phase"]
        invoked.append(phase["id"])
        report = _complete_phase(
            run_root,
            phase["id"],
            observations=2,
            passed=True,
        )
        return 0, report

    monkeypatch.setattr(
        SERIES,
        "_verify_series",
        lambda *_args, **_kwargs: {
            "passed": True,
            "required_consecutive_clean_runs": 2,
            "report_count": 2,
            "reasons": [],
        },
    )

    code, status = SERIES.run_series(
        run_root=run_root,
        metadata=metadata,
        max_hours=1,
        batch_observations=2,
        initial_backoff_seconds=1,
        max_backoff_seconds=2,
        between_batches_seconds=0,
        preflight_timeout=1,
        observation_timeout=1,
        max_model_calls=20,
        preflight_fn=_ready_preflight,
        batch_fn=batch,
        sleep_fn=lambda _seconds: None,
    )

    assert code == 0
    assert invoked == ["aa", "ab-round-1", "ab-round-2"]
    assert status["status"] == "complete"
    assert status["stop_reason"] == "gate5_series_passed"
    assert status["gate5_evidence"] is True
    assert status["completed_observations"] == 6
    assert status["remaining_observations"] == 0


def test_quota_interrupt_repreflights_and_resumes_same_phase(tmp_path):
    run_root, metadata = _fake_run(tmp_path)
    preflights = 0
    batches = 0
    sleeps: list[float] = []

    def preflight(**_kwargs):
        nonlocal preflights
        preflights += 1
        return 0, {"ready": True}

    def batch(**kwargs):
        nonlocal batches
        batches += 1
        if batches == 1:
            return 75, {
                "status": "interrupted",
                "interruption": {
                    "runner_error": {"code": "model_quota_exhausted"}
                },
            }
        report = _complete_phase(
            run_root,
            kwargs["phase"]["id"],
            observations=2,
            passed=False,
        )
        return 5, report

    code, status = SERIES.run_series(
        run_root=run_root,
        metadata=metadata,
        max_hours=1,
        batch_observations=2,
        initial_backoff_seconds=1,
        max_backoff_seconds=2,
        between_batches_seconds=0,
        preflight_timeout=1,
        observation_timeout=1,
        max_model_calls=20,
        preflight_fn=preflight,
        batch_fn=batch,
        sleep_fn=sleeps.append,
    )

    assert code == 5
    assert preflights == 2
    assert batches == 2
    assert sleeps == [1]
    assert status["stop_reason"] == "aa_noise_gate_failed"


def test_default_baseline_and_full_call_budget_are_explicit():
    text = SCRIPT.read_text(encoding="utf-8")

    assert SERIES.DEFAULT_BASELINE_REF == "da12de643c8a2355d019f40515766abf80a819df"
    assert "full three-phase series" in text
    assert "at least 481 calls" in text
    assert "never authenticates to or accesses PROCESIO" in text
