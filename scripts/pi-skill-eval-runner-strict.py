#!/usr/bin/env python3
"""Fixed-rubric wrapper around the local Pi behavioral evaluator.

The base runner provides corpus isolation, pinned-model execution, and a fresh
independent judge. This wrapper makes the grading rubric data rather than a
judge-generated interpretation: every juror receives the same ordered criterion
IDs and pass conditions, must return exactly those IDs, and cannot decide the
aggregate task-success value. The host computes task_success from the required
criterion booleans.
"""
from __future__ import annotations

import hashlib
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

_FIXED_JUDGE_SYSTEM = """You are an independent, strict response evaluator.
Judge only whether the candidate response satisfies the supplied fixed rubric
for the user task. Do not reward parroting, unsupported claims, unsafe actions,
or vague promises.

The candidate runs in a deliberately read-only evaluation context with no
network or mutation tools. Judge the quality and completeness of its decision,
workflow, implementation plan, and verification plan—not whether external or
repository mutations were executed. Treat an honest statement that execution
remains unverified as correct when a criterion asks for a plan. Penalize
fabricated claims that code, tests, API calls, or platform changes were completed.

The `behavioral_criteria` field is a JSON-serialized rubric object. It contains
an ordered `criteria` array. Every entry has an exact `id`, an exact pass
condition in `description`, and a `required` boolean.

Evaluate every supplied criterion independently. Return exactly one JSON object:
{"assertion_results":{"the_exact_supplied_id":true_or_false},"rationale":"brief evidence-based explanation"}

Contract:
- Copy every supplied criterion ID into assertion_results exactly once.
- Preserve spelling and case. Do not invent, rename, merge, split, omit, or add IDs.
- Every assertion value must be a JSON boolean.
- Apply each description as a binary pass condition. When evidence is absent or
  ambiguous, return false for that criterion.
- Do not output task_success. The host computes it from the required booleans.
- Base the verdict only on the candidate response and the supplied rubric.
- Do not use Markdown fences around the JSON.
"""

_CRITERION_ID_RE = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)+$")


def _normalize_rubric(raw: Any) -> tuple[dict[str, Any], bool]:
    """Return a canonical rubric and whether it is the legacy prose fallback."""
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            raise ValueError("expected_output or criteria is required")
        try:
            decoded = json.loads(text)
        except json.JSONDecodeError:
            return (
                {
                    "rubric_version": 0,
                    "criteria": [
                        {
                            "id": "expected_behavior",
                            "description": text,
                            "required": True,
                        }
                    ],
                },
                True,
            )
        raw = decoded

    if isinstance(raw, list):
        raw = {"rubric_version": 1, "criteria": raw}
    if not isinstance(raw, dict):
        raise ValueError("fixed rubric must be an object with a criteria array")

    version = raw.get("rubric_version")
    if not isinstance(version, int) or version < 1:
        raise ValueError("fixed rubric requires integer rubric_version >= 1")
    entries = raw.get("criteria")
    if not isinstance(entries, list) or not 2 <= len(entries) <= 8:
        raise ValueError("fixed rubric must contain 2 to 8 atomic criteria")

    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ValueError(f"criterion {index + 1} must be an object")
        criterion_id = entry.get("id")
        description = entry.get("description")
        required = entry.get("required")
        if not isinstance(criterion_id, str) or not _CRITERION_ID_RE.fullmatch(criterion_id):
            raise ValueError(
                f"criterion {index + 1} id must be descriptive lowercase snake_case"
            )
        if criterion_id in seen:
            raise ValueError(f"duplicate criterion id: {criterion_id}")
        if not isinstance(description, str) or not description.strip():
            raise ValueError(f"criterion {criterion_id!r} needs a non-empty description")
        if not isinstance(required, bool):
            raise ValueError(f"criterion {criterion_id!r} required must be boolean")
        seen.add(criterion_id)
        normalized.append(
            {
                "id": criterion_id,
                "description": description.strip(),
                "required": required,
            }
        )

    return {"rubric_version": version, "criteria": normalized}, False


def _rubric_fingerprint(rubric: dict[str, Any]) -> str:
    encoded = json.dumps(
        rubric,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_assertion_contract(
    assertions: Any,
    expected_ids: list[str] | tuple[str, ...],
) -> list[str]:
    """Require one boolean result for every and only supplied criterion ID."""
    if not isinstance(assertions, dict):
        return ["assertion_results must be an object"]

    expected = list(expected_ids)
    expected_set = set(expected)
    actual_set = {str(key) for key in assertions}
    violations: list[str] = []

    missing = [criterion_id for criterion_id in expected if criterion_id not in actual_set]
    unexpected = sorted(actual_set - expected_set)
    if missing:
        violations.append("missing assertion id(s): " + ", ".join(missing))
    if unexpected:
        violations.append("unexpected assertion id(s): " + ", ".join(unexpected))

    for criterion_id in expected:
        if criterion_id in assertions and not isinstance(assertions[criterion_id], bool):
            violations.append(f"assertion value must be boolean: {criterion_id!r}")
    return violations


def _normalized_assertions(assertions: Any, expected_ids: list[str]) -> dict[str, bool]:
    source = assertions if isinstance(assertions, dict) else {}
    return {
        criterion_id: source.get(criterion_id) is True
        for criterion_id in expected_ids
    }


def evaluate_request(request: dict[str, Any]) -> dict[str, Any]:
    """Run one evaluation and enforce the fixed-rubric contract in host code."""
    raw_rubric = request.get("criteria")
    if raw_rubric is None:
        raw_rubric = request.get("expected_output")
    rubric, legacy = _normalize_rubric(raw_rubric)
    criteria = rubric["criteria"]
    criterion_ids = [str(entry["id"]) for entry in criteria]
    required_ids = [str(entry["id"]) for entry in criteria if entry["required"] is True]

    forwarded = dict(request)
    forwarded["expected_output"] = json.dumps(
        rubric,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )

    previous = BASE._JUDGE_SYSTEM
    BASE._JUDGE_SYSTEM = _FIXED_JUDGE_SYSTEM
    try:
        result = BASE.evaluate_request(forwarded)
    finally:
        BASE._JUDGE_SYSTEM = previous

    raw_assertions = result.get("assertion_results")
    violations = validate_assertion_contract(raw_assertions, criterion_ids)
    assertions = _normalized_assertions(raw_assertions, criterion_ids)

    result["assertion_results"] = assertions
    result["task_success"] = (
        not violations and all(assertions[criterion_id] for criterion_id in required_ids)
    )
    result["grader_contract"] = (
        "legacy-prose-rubric-v1" if legacy else "fixed-jury-rubric-v2"
    )
    result["rubric_version"] = rubric["rubric_version"]
    result["criterion_ids"] = criterion_ids
    result["required_criterion_ids"] = required_ids
    result["criteria_fingerprint"] = _rubric_fingerprint(rubric)
    if violations:
        result["grader_contract_violations"] = violations
    else:
        result.pop("grader_contract_violations", None)
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
                "next_action": "Correct the fixed rubric or local model configuration and rerun.",
            }
        }
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
        return 2

    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
