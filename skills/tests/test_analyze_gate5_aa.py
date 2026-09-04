from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "analyze-gate5-aa.py"
SPEC = importlib.util.spec_from_file_location("analyze_gate5_aa", SCRIPT)
assert SPEC and SPEC.loader
ANALYZER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ANALYZER)


def _row(
    *,
    sequence: int,
    case_id: str,
    repetition: int,
    label: str,
    success: bool,
    selected: str | None = "demo",
) -> dict:
    return {
        "sequence": sequence,
        "case_id": case_id,
        "repetition": repetition,
        "variant_label": label,
        "expected_skill": "demo",
        "forbidden_skills": [],
        "selected_skill": selected,
        "task_success": success,
        "response": f"response-{case_id}-{repetition}-{label}",
        "assertion_results": {"meets_expected_behavior": success, "uses_correct_boundary": True},
        "judge_rationale": "pass" if success else "missing expected behavior",
    }


def _fixture_run(tmp_path: Path) -> Path:
    run = tmp_path / "run"
    results = run / "results"
    results.mkdir(parents=True)
    report = {
        "mode": "aa",
        "case_count": 2,
        "repetitions": 2,
        "blind_label_mapping": {"corpus-a": "candidate", "corpus-b": "baseline"},
        "candidate_fingerprint": "same",
        "baseline_fingerprint": "same",
        "gate": {
            "mode": "aa",
            "passed": False,
            "reasons": ["A/A task_success_rate_delta exceeds noise limit 0.05"],
        },
    }
    (results / "report.json").write_text(json.dumps(report), encoding="utf-8")
    rows = [
        _row(sequence=1, case_id="a", repetition=0, label="corpus-a", success=True),
        _row(sequence=2, case_id="a", repetition=0, label="corpus-b", success=False),
        _row(sequence=3, case_id="a", repetition=1, label="corpus-a", success=True),
        _row(sequence=4, case_id="a", repetition=1, label="corpus-b", success=True),
        _row(sequence=5, case_id="b", repetition=0, label="corpus-a", success=False),
        _row(sequence=6, case_id="b", repetition=0, label="corpus-b", success=False),
        _row(sequence=7, case_id="b", repetition=1, label="corpus-a", success=True),
        _row(sequence=8, case_id="b", repetition=1, label="corpus-b", success=True),
    ]
    (results / "runs.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
    )
    return run


def test_analyzer_pairs_identical_arms_and_surfaces_disagreements(tmp_path):
    result = ANALYZER.analyze_run(_fixture_run(tmp_path), response_chars=100)

    assert result["byte_identical_corpora"] is True
    assert result["labels_are_semantically_arbitrary"] is True
    assert result["arm_summary"]["candidate"]["task_successes"] == 3
    assert result["arm_summary"]["baseline"]["task_successes"] == 2
    assert result["paired_summary"]["pairs"] == 4
    assert result["paired_summary"]["candidate_only_passes"] == 1
    assert result["paired_summary"]["baseline_only_passes"] == 0
    assert result["paired_summary"]["both_fail"] == 1
    assert result["paired_summary"]["selection_disagreements"] == 0
    assert result["paired_summary"]["discordant_pair_exact_sign_test_p"] == 1.0
    assert len(result["review_queue"]) == 2
    failed = result["review_queue"][0]["arms"]["baseline"]
    assert failed["false_assertions"] == ["meets_expected_behavior"]


def test_analyzer_rejects_nonidentical_aa_fingerprints(tmp_path):
    run = _fixture_run(tmp_path)
    report_path = run / "results" / "report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["baseline_fingerprint"] = "different"
    report_path.write_text(json.dumps(report), encoding="utf-8")

    with pytest.raises(ValueError, match="byte-identical"):
        ANALYZER.analyze_run(run)


def test_analyzer_rejects_incomplete_pair(tmp_path):
    run = _fixture_run(tmp_path)
    rows_path = run / "results" / "runs.jsonl"
    rows = rows_path.read_text(encoding="utf-8").splitlines()
    rows_path.write_text("\n".join(rows[:-1]) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="complete report expects"):
        ANALYZER.analyze_run(run)


def test_exact_sign_test_is_diagnostic_only():
    assert ANALYZER._exact_two_sided_sign_test(3, 0) == 0.25
    assert ANALYZER._exact_two_sided_sign_test(0, 0) == 1.0
