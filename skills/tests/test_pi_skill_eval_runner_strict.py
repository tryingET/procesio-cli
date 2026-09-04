from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "pi-skill-eval-runner-strict.py"
SPEC = importlib.util.spec_from_file_location("pi_skill_eval_runner_strict", SCRIPT)
assert SPEC and SPEC.loader
RUNNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNNER)


def _rubric() -> dict:
    return {
        "rubric_version": 1,
        "criteria": [
            {
                "id": "treats_timeout_as_unknown",
                "description": "Pass only when timeout is classified as unknown.",
                "required": True,
            },
            {
                "id": "reconciles_prior_instance",
                "description": "Pass only when existing instances are reconciled first.",
                "required": True,
            },
            {
                "id": "guards_duplicate_side_effects",
                "description": "Pass only when duplicate side effects are guarded.",
                "required": True,
            },
        ],
    }


def test_fixed_rubric_normalization_preserves_order_and_wording():
    rubric, legacy = RUNNER._normalize_rubric(_rubric())

    assert legacy is False
    assert rubric == _rubric()
    assert [entry["id"] for entry in rubric["criteria"]] == [
        "treats_timeout_as_unknown",
        "reconciles_prior_instance",
        "guards_duplicate_side_effects",
    ]


def test_fixed_rubric_rejects_duplicate_invalid_or_missing_criteria():
    duplicate = _rubric()
    duplicate["criteria"][1]["id"] = duplicate["criteria"][0]["id"]
    with pytest.raises(ValueError, match="duplicate criterion id"):
        RUNNER._normalize_rubric(duplicate)

    invalid = _rubric()
    invalid["criteria"][0]["id"] = "Timeout Check"
    with pytest.raises(ValueError, match="snake_case"):
        RUNNER._normalize_rubric(invalid)

    with pytest.raises(ValueError, match="2 to 8"):
        RUNNER._normalize_rubric(
            {
                "rubric_version": 1,
                "criteria": [_rubric()["criteria"][0]],
            }
        )


def test_exact_assertion_ids_and_booleans_are_required():
    expected = [entry["id"] for entry in _rubric()["criteria"]]

    assert RUNNER.validate_assertion_contract(
        {criterion_id: True for criterion_id in expected}, expected
    ) == []

    violations = RUNNER.validate_assertion_contract(
        {
            expected[0]: True,
            expected[1]: "true",
            "invented_check": True,
        },
        expected,
    )
    assert any("missing assertion" in item and expected[2] in item for item in violations)
    assert any("unexpected assertion" in item and "invented_check" in item for item in violations)
    assert any("must be boolean" in item and expected[1] in item for item in violations)


def test_host_computes_success_from_fixed_required_booleans(monkeypatch):
    captured = {}

    def fake_base(request):
        captured.update(request)
        return {
            "selected_skill": "procesio-cli",
            # The model-level aggregate is deliberately false. The fixed wrapper
            # must ignore it and compute the aggregate from the supplied IDs.
            "task_success": False,
            "response": "Safe response",
            "assertion_results": {
                "treats_timeout_as_unknown": True,
                "reconciles_prior_instance": True,
                "guards_duplicate_side_effects": True,
            },
            "judge_rationale": "All fixed criteria are present.",
        }

    monkeypatch.setattr(RUNNER.BASE, "evaluate_request", fake_base)
    result = RUNNER.evaluate_request(
        {
            "skills_root": "unused-by-fake",
            "task": "Retry now",
            "expected_output": _rubric(),
        }
    )

    forwarded = json.loads(captured["expected_output"])
    assert forwarded == _rubric()
    assert result["task_success"] is True
    assert result["grader_contract"] == "fixed-jury-rubric-v2"
    assert result["criterion_ids"] == [
        "treats_timeout_as_unknown",
        "reconciles_prior_instance",
        "guards_duplicate_side_effects",
    ]
    assert result["required_criterion_ids"] == result["criterion_ids"]
    assert len(result["criteria_fingerprint"]) == 64
    assert "grader_contract_violations" not in result


def test_missing_or_invented_juror_key_forces_failure(monkeypatch):
    def fake_base(_request):
        return {
            "selected_skill": "procesio-cli",
            "task_success": True,
            "response": "Answer",
            "assertion_results": {
                "treats_timeout_as_unknown": True,
                "reconciles_prior_instance": True,
                "different_third_check": True,
            },
        }

    monkeypatch.setattr(RUNNER.BASE, "evaluate_request", fake_base)
    result = RUNNER.evaluate_request(
        {"task": "Retry", "expected_output": _rubric()}
    )

    assert result["task_success"] is False
    assert result["assertion_results"] == {
        "treats_timeout_as_unknown": True,
        "reconciles_prior_instance": True,
        "guards_duplicate_side_effects": False,
    }
    violations = result["grader_contract_violations"]
    assert any("guards_duplicate_side_effects" in item for item in violations)
    assert any("different_third_check" in item for item in violations)


def test_legacy_prose_is_supported_but_not_mislabeled_as_fixed_rubric():
    rubric, legacy = RUNNER._normalize_rubric("Be safe and actionable.")

    assert legacy is True
    assert rubric["rubric_version"] == 0
    assert rubric["criteria"] == [
        {
            "id": "expected_behavior",
            "description": "Be safe and actionable.",
            "required": True,
        }
    ]


def test_judge_prompt_forbids_dynamic_criterion_decomposition():
    prompt = RUNNER._FIXED_JUDGE_SYSTEM

    assert "same ordered criterion" in RUNNER.__doc__
    assert "Do not invent, rename, merge, split, omit, or add IDs" in prompt
    assert "Do not output task_success" in prompt
    assert "host computes it" in prompt
    assert "read-only evaluation context" in prompt
