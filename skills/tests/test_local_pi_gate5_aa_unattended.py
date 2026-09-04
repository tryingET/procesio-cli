from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "run-local-pi-gate5-aa-unattended.py"
SPEC = importlib.util.spec_from_file_location("run_local_pi_gate5_aa_unattended", SCRIPT)
assert SPEC and SPEC.loader
RUNNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNNER)


def _make_run(tmp_path: Path, *, total: int = 4) -> Path:
    run = tmp_path / "run"
    (run / "results").mkdir(parents=True)
    (run / "run-metadata.json").write_text(
        json.dumps(
            {
                "model": "provider/model",
                "provider": None,
                "thinking": "medium",
                "case_count": 1,
                "repetitions": total // 2,
                "seed": 7,
            }
        ),
        encoding="utf-8",
    )
    return run


def _append_rows(run: Path, count: int) -> None:
    path = run / "results" / "runs.jsonl"
    with path.open("a", encoding="utf-8") as stream:
        start = RUNNER._checkpoint_count(run)
        for index in range(count):
            stream.write(json.dumps({"sequence": start + index + 1}) + "\n")


def test_quota_backoff_then_batches_complete(tmp_path):
    run = _make_run(tmp_path)
    preflights = iter(
        [
            (2, {"ready": False, "failure_class": "quota_exhausted"}),
            (0, {"ready": True}),
        ]
    )
    batch_calls: list[int] = []

    def preflight_fn(**_kwargs):
        return next(preflights)

    def batch_fn(*, run_root, observations, **_kwargs):
        batch_calls.append(observations)
        _append_rows(run_root, observations)
        if RUNNER._checkpoint_count(run_root) < 4:
            return 75, {
                "kind": "gate5-aa-checkpoint",
                "status": "paused",
                "runner_error": None,
            }
        report = {"gate": {"passed": True}, "summary": {"ok": True}}
        (run_root / "results" / "report.json").write_text(
            json.dumps(report), encoding="utf-8"
        )
        return 0, {
            "kind": "gate5-aa-noise-floor",
            "gate5_evidence": True,
            "gate": report["gate"],
            "summary": report["summary"],
        }

    now = [0.0]
    sleeps: list[float] = []

    def monotonic():
        return now[0]

    def sleep(seconds):
        sleeps.append(seconds)
        now[0] += seconds

    code, result = RUNNER.run_unattended(
        run_root=run,
        max_hours=1,
        batch_observations=2,
        initial_backoff_seconds=5,
        max_backoff_seconds=20,
        between_batches_seconds=1,
        preflight_timeout=10,
        observation_timeout=10,
        max_model_calls=10,
        preflight_fn=preflight_fn,
        batch_fn=batch_fn,
        sleep_fn=sleep,
        monotonic_fn=monotonic,
    )

    assert code == 0
    assert result["status"] == "complete"
    assert result["stop_reason"] == "aa_passed"
    assert result["completed_observations"] == 4
    assert result["model_calls_upper_bound"] == 10
    assert batch_calls == [2, 2]
    assert sleeps == [5, 1]


def test_repeated_quota_stops_at_deadline_without_batch(tmp_path):
    run = _make_run(tmp_path)
    now = [0.0]

    def preflight_fn(**_kwargs):
        return 2, {"ready": False, "failure_class": "quota_exhausted"}

    def batch_fn(**_kwargs):
        raise AssertionError("batch must not start")

    def monotonic():
        return now[0]

    def sleep(seconds):
        now[0] += seconds

    code, result = RUNNER.run_unattended(
        run_root=run,
        max_hours=0.001,
        batch_observations=2,
        initial_backoff_seconds=5,
        max_backoff_seconds=20,
        between_batches_seconds=0,
        preflight_timeout=10,
        observation_timeout=10,
        max_model_calls=10,
        preflight_fn=preflight_fn,
        batch_fn=batch_fn,
        sleep_fn=sleep,
        monotonic_fn=monotonic,
    )

    assert code == 75
    assert result["status"] == "paused"
    assert result["stop_reason"] == "wall_clock_deadline"
    assert result["completed_observations"] == 0
    assert result["preflight_attempts"] == 1


def test_nonquota_preflight_error_stops_immediately(tmp_path):
    run = _make_run(tmp_path)

    def preflight_fn(**_kwargs):
        return 2, {"ready": False, "failure_class": "model_not_available"}

    code, result = RUNNER.run_unattended(
        run_root=run,
        max_hours=1,
        batch_observations=2,
        initial_backoff_seconds=5,
        max_backoff_seconds=20,
        between_batches_seconds=0,
        preflight_timeout=10,
        observation_timeout=10,
        max_model_calls=10,
        preflight_fn=preflight_fn,
        batch_fn=lambda **_: (_ for _ in ()).throw(AssertionError()),
        sleep_fn=lambda _: None,
        monotonic_fn=lambda: 0,
    )

    assert code == 2
    assert result["status"] == "error"
    assert result["stop_reason"] == "preflight_non_retryable"


def test_nested_quota_error_is_retryable():
    assert RUNNER._is_quota_or_rate_limit(
        {"runner_error": {"code": "model_quota_exhausted"}}
    )
    assert not RUNNER._is_quota_or_rate_limit(
        {"runner_error": {"code": "model_not_available"}}
    )
