from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "pi-skill-eval-runner-strict.py"
SPEC = importlib.util.spec_from_file_location("pi_skill_eval_runner_strict", SCRIPT)
assert SPEC and SPEC.loader
RUNNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNNER)


def test_placeholder_assertion_cannot_count_as_behavioral_evidence():
    violations = RUNNER.validate_assertion_contract(
        {"short_snake_case_check": True}
    )

    assert violations
    assert any("2 to 5" in item for item in violations)
    assert any("generic assertion key" in item for item in violations)


def test_distinct_criteria_specific_boolean_assertions_pass_contract():
    assert RUNNER.validate_assertion_contract(
        {
            "treats_timeout_as_unknown": True,
            "reconciles_prior_instance": True,
            "guards_duplicate_side_effects": True,
        }
    ) == []


def test_non_boolean_assertion_and_vague_key_fail_contract():
    violations = RUNNER.validate_assertion_contract(
        {"safe": "true", "reconciles_prior_instance": True}
    )

    assert any("descriptive snake_case" in item for item in violations)
    assert any("generic assertion key" in item for item in violations)
    assert any("must be boolean" in item for item in violations)


def test_strict_judge_prompt_requires_multiple_specific_checks():
    prompt = RUNNER._STRICT_JUDGE_SYSTEM

    assert "2 to 5" in prompt
    assert "distinct requirement" in prompt
    assert "no_blind_retry" in prompt
    assert "short_snake_case_check" in prompt
    assert "Do not use placeholder" in prompt
