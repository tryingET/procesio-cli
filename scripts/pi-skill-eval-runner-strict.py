#!/usr/bin/env python3
"""Strict wrapper around the local Pi behavioral-evaluation runner.

The base runner provides corpus isolation, pinned-model execution, and a fresh
independent judge. This wrapper tightens the judge contract so a generic
placeholder assertion cannot count as behavioral evidence.
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any

BASE_PATH = Path(__file__).with_name("pi-skill-eval-runner.py")
SPEC = importlib.util.spec_from_file_location("pi_skill_eval_runner_base", BASE_PATH)
if SPEC is None or SPEC.loader is None:  # pragma: no cover - import safety
    raise RuntimeError(f"cannot load base runner: {BASE_PATH}")
BASE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BASE)

_STRICT_JUDGE_SYSTEM = """You are an independent, strict response evaluator.
Judge only whether the candidate response substantively satisfies the supplied
behavioral criteria for the user task. Do not reward parroting, unsupported
claims, unsafe actions, or vague promises.

The candidate runs in a deliberately read-only evaluation context with no
network or mutation tools. Judge the quality and completeness of the decision,
workflow, implementation plan, and verification plan—not whether external or
repository mutations were actually executed. Treat an honest statement that
execution remains unverified as correct when the criteria ask for a plan. Penalize
fabricated claims that code, tests, API calls, or platform changes were completed.

Return exactly one JSON object with this shape:
{"task_success":true_or_false,"assertion_results":{"criterion_specific_snake_case":true_or_false,"another_specific_check":true_or_false},"rationale":"brief evidence-based explanation"}

Contract:
- Produce 2 to 5 assertion_results entries.
- Derive every assertion directly from a distinct requirement in behavioral_criteria.
- Use descriptive lowercase snake_case keys, such as no_blind_retry or reconciles_prior_instance.
- Do not use placeholder or generic keys such as short_snake_case_check, check, ok, pass, success, safe, or complete.
- Every assertion value must be a JSON boolean.
- task_success may be true only when every required criterion is represented and every assertion is true.
- Base the verdict on the candidate response, not on what a better answer could have said.
Do not use Markdown fences around the JSON.
"""

_KEY_RE = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)+$")
_GENERIC_KEYS = {
    "short_snake_case_check",
    "check",
    "criterion",
    "criteria",
    "ok",
    "pass",
    "passed",
    "success",
    "safe",
    "complete",
}


def validate_assertion_contract(assertions: Any) -> list[str]:
    """Return grader-contract violations without interpreting task semantics."""
    violations: list[str] = []
    if not isinstance(assertions, dict):
        return ["assertion_results must be an object"]
    if not 2 <= len(assertions) <= 5:
        violations.append("assertion_results must contain 2 to 5 criteria-specific entries")

    for raw_key, value in assertions.items():
        key = str(raw_key)
        if not _KEY_RE.fullmatch(key):
            violations.append(f"assertion key is not descriptive snake_case: {key!r}")
        if key in _GENERIC_KEYS:
            violations.append(f"generic assertion key is forbidden: {key!r}")
        if not isinstance(value, bool):
            violations.append(f"assertion value must be boolean: {key!r}")
    return violations


def evaluate_request(request: dict[str, Any]) -> dict[str, Any]:
    """Run the base evaluator, then enforce the stronger grader contract."""
    previous = BASE._JUDGE_SYSTEM
    BASE._JUDGE_SYSTEM = _STRICT_JUDGE_SYSTEM
    try:
        result = BASE.evaluate_request(request)
    finally:
        BASE._JUDGE_SYSTEM = previous

    violations = validate_assertion_contract(result.get("assertion_results"))
    result["grader_contract"] = "criteria-specific-v1"
    if violations:
        result["task_success"] = False
        result["grader_contract_violations"] = violations
    return result


def main() -> int:
    try:
        request = json.loads(sys.stdin.read())
        if not isinstance(request, dict):
            raise ValueError("stdin must contain one JSON object")
        result = evaluate_request(request)
    except BASE.PiRunnerError as exc:
        print(json.dumps(exc.public_result(), ensure_ascii=False, separators=(",", ":")))
        return 2
    except Exception as exc:  # noqa: BLE001 - emit one safe actionable failure
        result = {
            "runner_error": {
                "code": "strict_runner_failure",
                "message": str(exc)[:500],
                "next_action": "Correct the local input or model configuration and rerun.",
            }
        }
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
        return 2

    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
