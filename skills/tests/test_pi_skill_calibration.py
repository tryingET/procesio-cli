from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "run-pi-skill-calibration.py"
SPEC = importlib.util.spec_from_file_location("pi_skill_calibration", SCRIPT)
assert SPEC and SPEC.loader
CAL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CAL)


def _case(case_id: str, expected_skill: str | None) -> dict:
    return {
        "id": case_id,
        "prompt": f"Prompt for {case_id}",
        "expected_skill": expected_skill,
        "forbidden_skills": [],
        "expected_output": f"Criteria for {case_id}",
    }


def test_load_cases_uses_balanced_default_order(tmp_path):
    rows = [
        _case("unrelated-postgres", None),
        _case("mcp-resource-change", "procesio-cli-maintainer"),
        _case("blanket-nolock", "sql-server-optimizer"),
        _case("capacity-without-runtime", "procesio-platform-advisor"),
        _case("unknown-process-outcome", "procesio-cli"),
    ]
    path = tmp_path / "behavioral.json"
    path.write_text(json.dumps({"cases": rows}), encoding="utf-8")

    loaded = CAL._load_cases(path)

    assert [row["id"] for row in loaded] == list(CAL.DEFAULT_CASE_IDS)
    assert {row["expected_skill"] for row in loaded} == {
        "procesio-cli",
        "procesio-platform-advisor",
        "sql-server-optimizer",
        "procesio-cli-maintainer",
        None,
    }


def test_grade_case_requires_specific_strict_assertions():
    case = _case("unknown-process-outcome", "procesio-cli")
    passing = CAL._grade_case(
        case,
        {
            "selected_skill": "procesio-cli",
            "task_success": True,
            "grader_contract": "criteria-specific-v1",
            "assertion_results": {
                "treats_timeout_as_unknown": True,
                "reconciles_before_retry": True,
            },
        },
    )
    assert passing["passed"] is True

    generic = CAL._grade_case(
        case,
        {
            "selected_skill": "procesio-cli",
            "task_success": False,
            "grader_contract": "criteria-specific-v1",
            "assertion_results": {"short_snake_case_check": True},
            "grader_contract_violations": ["generic assertion key is forbidden"],
        },
    )
    assert generic["passed"] is False
    assert "strict grader contract violation" in generic["reasons"]
    assert "fewer than two criteria-specific assertions" in generic["reasons"]


def test_run_calibration_reports_compact_balanced_summary(monkeypatch, tmp_path):
    cases = [
        _case("unknown-process-outcome", "procesio-cli"),
        _case("capacity-without-runtime", "procesio-platform-advisor"),
        _case("blanket-nolock", "sql-server-optimizer"),
        _case("mcp-resource-change", "procesio-cli-maintainer"),
        _case("unrelated-postgres", None),
    ]
    calls: list[str] = []

    def fake_invoke(*, runner, skills_root, case, timeout):
        calls.append(case["id"])
        return {
            "selected_skill": case["expected_skill"],
            "task_success": True,
            "grader_contract": "criteria-specific-v1",
            "assertion_results": {
                "matches_expected_behavior": True,
                "avoids_forbidden_behavior": True,
            },
            "judge_rationale": "Meets both distinct criteria.",
            "duration_ms": 12,
        }

    monkeypatch.setenv("PI_EVAL_MODEL", "opencode-go/muse-spark-1.3-contributor")
    monkeypatch.setenv("PI_EVAL_THINKING", "low")
    summary, details = CAL.run_calibration(
        cases=cases,
        skills_root=tmp_path,
        runner=tmp_path / "runner.py",
        timeout=600,
        invoke=fake_invoke,
    )

    assert calls == [case["id"] for case in cases]
    assert summary["model"] == "opencode-go/muse-spark-1.3-contributor"
    assert summary["expected_model_calls"] == 10
    assert summary["passed_cases"] == 5
    assert summary["failed_cases"] == 0
    assert summary["all_passed"] is True
    assert summary["gate5_evidence"] is False
    assert len(details) == 5


def test_forbidden_skill_collision_fails_even_when_judge_passes():
    case = {
        **_case("advice", "procesio-platform-advisor"),
        "forbidden_skills": ["procesio-cli"],
    }
    grade = CAL._grade_case(
        case,
        {
            "selected_skill": "procesio-cli",
            "task_success": True,
            "grader_contract": "criteria-specific-v1",
            "assertion_results": {
                "assesses_fit": True,
                "avoids_mutation": True,
            },
        },
    )

    assert grade["passed"] is False
    assert "forbidden skill collision: 'procesio-cli'" in grade["reasons"]
