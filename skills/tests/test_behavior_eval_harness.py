from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "run-skill-behavior-evals.py"
SPEC = importlib.util.spec_from_file_location("run_skill_behavior_evals", SCRIPT)
assert SPEC and SPEC.loader
runner = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = runner
SPEC.loader.exec_module(runner)


def _fixture_corpora(tmp_path):
    candidate = tmp_path / "candidate"
    baseline = tmp_path / "baseline"
    for root in (candidate, baseline):
        (root / "demo").mkdir(parents=True)
        (root / "demo" / "SKILL.md").write_text(
            "---\nname: demo\ndescription: Use when testing skills.\n---\n# Demo\n",
            encoding="utf-8",
        )
    evals = tmp_path / "evals.json"
    evals.write_text(json.dumps({"cases": [{
        "id": "x", "prompt": "test skills", "expected_skill": "demo",
        "forbidden_skills": [], "expected_output": "select demo",
    }]}), encoding="utf-8")
    thresholds = tmp_path / "thresholds.json"
    thresholds.write_text(json.dumps({
        "minimum_repetitions": 1,
        "max_aa_selection_delta": 0,
        "max_aa_task_success_delta": 0,
        "max_aa_collision_delta": 0,
        "min_selection_accuracy": 1,
        "max_collision_rate": 0,
        "min_task_success_delta": 0,
    }), encoding="utf-8")
    return candidate, baseline, evals, thresholds


def _command(tmp_path, candidate, baseline, evals, thresholds, *extra, runner_path=None):
    fixture = runner_path or ROOT / "skills" / "tests" / "fixtures" / "skill_eval_runner.py"
    return [
        sys.executable, str(SCRIPT),
        "--candidate-root", str(candidate), "--baseline-root", str(baseline),
        "--evals", str(evals), "--thresholds", str(thresholds),
        "--runner", f"{sys.executable} {fixture}",
        "--workspace", str(tmp_path / "out"), "--repetitions", "1",
        *extra,
    ]


def test_windows_runner_split_preserves_backslashes_and_removes_quote_wrappers():
    command = (
        r'"C:\Program Files\Python\python.exe" '
        r'C:\repo\.venv\Scripts\runner.py'
    )
    assert runner._split_runner(command, platform="nt") == [
        r"C:\Program Files\Python\python.exe",
        r"C:\repo\.venv\Scripts\runner.py",
    ]


def test_paired_runner_writes_blinded_report(tmp_path):
    candidate, baseline, evals, thresholds = _fixture_corpora(tmp_path)
    proc = subprocess.run(
        _command(tmp_path, candidate, baseline, evals, thresholds),
        text=True, capture_output=True,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    report = json.loads((tmp_path / "out" / "report.json").read_text())
    assert report["mode"] == "ab"
    assert report["status"] == "complete"
    assert report["summary"]["candidate"]["selection_accuracy"] == 1
    assert report["summary"]["baseline"]["selection_accuracy"] == 1
    assert set(report["blind_label_mapping"]) == {"corpus-a", "corpus-b"}


def test_aa_mode_accepts_identical_corpora_inside_noise_floor(tmp_path):
    candidate, baseline, evals, thresholds = _fixture_corpora(tmp_path)
    proc = subprocess.run(
        _command(tmp_path, candidate, baseline, evals, thresholds, "--mode", "aa"),
        text=True, capture_output=True,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    report = json.loads((tmp_path / "out" / "report.json").read_text())
    assert report["mode"] == "aa"
    assert report["gate"]["passed"] is True


def test_aa_mode_rejects_nonidentical_corpora(tmp_path):
    candidate, baseline, evals, thresholds = _fixture_corpora(tmp_path)
    (baseline / "demo" / "SKILL.md").write_text("different", encoding="utf-8")
    proc = subprocess.run(
        _command(tmp_path, candidate, baseline, evals, thresholds, "--mode", "aa"),
        text=True, capture_output=True,
    )
    assert proc.returncode != 0
    assert "byte-identical" in proc.stderr


def test_checkpoint_batch_resumes_without_overwriting_completed_rows(tmp_path):
    candidate, baseline, evals, thresholds = _fixture_corpora(tmp_path)
    first = subprocess.run(
        _command(
            tmp_path, candidate, baseline, evals, thresholds,
            "--mode", "aa", "--max-new-observations", "1",
        ),
        text=True, capture_output=True,
    )
    assert first.returncode == runner.INCOMPLETE_EXIT, first.stderr or first.stdout
    partial = json.loads(first.stdout)
    assert partial["status"] == "paused"
    assert partial["completed_observations"] == 1
    runs_path = tmp_path / "out" / "runs.jsonl"
    first_row = runs_path.read_text(encoding="utf-8")

    second = subprocess.run(
        _command(
            tmp_path, candidate, baseline, evals, thresholds,
            "--mode", "aa", "--resume",
        ),
        text=True, capture_output=True,
    )
    assert second.returncode == 0, second.stderr or second.stdout
    final_rows = runs_path.read_text(encoding="utf-8").splitlines()
    assert len(final_rows) == 2
    assert final_rows[0] + "\n" == first_row
    assert (tmp_path / "out" / "report.json").is_file()
    assert not (tmp_path / "out" / "partial-report.json").exists()


def test_structured_quota_error_writes_resumable_partial_report(tmp_path):
    candidate, baseline, evals, thresholds = _fixture_corpora(tmp_path)
    stateful = tmp_path / "stateful_runner.py"
    stateful.write_text(
        """import json, pathlib, sys
request = json.load(sys.stdin)
state = pathlib.Path(__file__).with_suffix('.count')
count = int(state.read_text()) if state.exists() else 0
count += 1
state.write_text(str(count))
if count == 2:
    print(json.dumps({'runner_error': {'code': 'model_quota_exhausted', 'message': 'quota gone'}}))
    raise SystemExit(2)
print(json.dumps({'selected_skill': 'demo', 'task_success': True, 'response': request['run_id'], 'total_tokens': 10}))
""",
        encoding="utf-8",
    )

    first = subprocess.run(
        _command(
            tmp_path, candidate, baseline, evals, thresholds,
            "--mode", "aa", runner_path=stateful,
        ),
        text=True, capture_output=True,
    )
    assert first.returncode == runner.INCOMPLETE_EXIT, first.stderr or first.stdout
    partial = json.loads((tmp_path / "out" / "partial-report.json").read_text())
    assert partial["status"] == "interrupted"
    assert partial["resumable"] is True
    assert partial["completed_observations"] == 1
    assert partial["interruption"]["runner_error"]["code"] == "model_quota_exhausted"

    second = subprocess.run(
        _command(
            tmp_path, candidate, baseline, evals, thresholds,
            "--mode", "aa", "--resume", runner_path=stateful,
        ),
        text=True, capture_output=True,
    )
    assert second.returncode == 0, second.stderr or second.stdout
    assert len((tmp_path / "out" / "runs.jsonl").read_text().splitlines()) == 2


def test_resume_rejects_changed_experiment_settings(tmp_path):
    candidate, baseline, evals, thresholds = _fixture_corpora(tmp_path)
    first = subprocess.run(
        _command(
            tmp_path, candidate, baseline, evals, thresholds,
            "--mode", "aa", "--max-new-observations", "1",
        ),
        text=True, capture_output=True,
    )
    assert first.returncode == runner.INCOMPLETE_EXIT

    changed = subprocess.run(
        _command(
            tmp_path, candidate, baseline, evals, thresholds,
            "--mode", "aa", "--resume", "--seed", "999",
        ),
        text=True, capture_output=True,
    )
    assert changed.returncode != 0
    assert "cannot resume" in changed.stderr


def test_committed_dogfood_is_not_misrepresented_as_release_grade():
    record = json.loads((ROOT / "skills" / "evals" / "gate5-dogfood.json").read_text())
    assert record["release_gate_passed"] is False
    assert record["fresh_context"] is False
    assert record["blinded"] is False
    assert all(row["task_success"] for row in record["observations"])
