from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_paired_runner_writes_blinded_report(tmp_path):
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
        "forbidden_skills": [],
    }]}), encoding="utf-8")
    thresholds = tmp_path / "thresholds.json"
    thresholds.write_text(json.dumps({
        "minimum_repetitions": 1,
        "min_selection_accuracy": 1,
        "max_collision_rate": 0,
        "min_task_success_delta": 0,
    }), encoding="utf-8")
    fixture = ROOT / "skills" / "tests" / "fixtures" / "skill_eval_runner.py"
    command = [
        sys.executable, str(ROOT / "scripts" / "run-skill-behavior-evals.py"),
        "--candidate-root", str(candidate), "--baseline-root", str(baseline),
        "--evals", str(evals), "--thresholds", str(thresholds),
        "--runner", f"{sys.executable} {fixture}",
        "--workspace", str(tmp_path / "out"), "--repetitions", "1",
    ]
    proc = subprocess.run(command, text=True, capture_output=True)
    assert proc.returncode == 0, proc.stderr or proc.stdout
    report = json.loads((tmp_path / "out" / "report.json").read_text())
    assert report["summary"]["candidate"]["selection_accuracy"] == 1
    assert report["summary"]["baseline"]["selection_accuracy"] == 1
    assert set(report["blind_label_mapping"]) == {"corpus-a", "corpus-b"}


def test_committed_dogfood_is_not_misrepresented_as_release_grade():
    record = json.loads((ROOT / "skills" / "evals" / "gate5-dogfood.json").read_text())
    assert record["release_gate_passed"] is False
    assert record["fresh_context"] is False
    assert record["blinded"] is False
    assert all(row["task_success"] for row in record["observations"])
