#!/usr/bin/env python3
"""Run a small, balanced, single-corpus Pi skill calibration.

This is deliberately cheaper than Gate 5. The default five cases cover the four
published skills plus one expected abstention. Each case is evaluated by the
fixed-rubric Pi runner, which makes one fresh response call and one fresh judge
call. The default calibration therefore uses ten model calls.

The result is provisional calibration only. It neither compares the frozen
baseline nor satisfies the repeated blinded A/A and A/B Gate 5 contract.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SKILLS = ROOT / "skills"
DEFAULT_EVALS = DEFAULT_SKILLS / "evals" / "behavioral.json"
DEFAULT_RUNNER = ROOT / "scripts" / "pi-skill-eval-runner-strict.py"
DEFAULT_OUT = ROOT / "scratchpad" / "pi-skill-calibration-report.json"
DEFAULT_CASE_IDS = (
    "unknown-process-outcome",
    "capacity-without-runtime",
    "blanket-nolock",
    "mcp-resource-change",
    "unrelated-postgres",
)


def _criterion_ids(case: dict[str, Any]) -> list[str]:
    rubric = case.get("expected_output")
    criteria = rubric.get("criteria") if isinstance(rubric, dict) else None
    if not isinstance(criteria, list) or not criteria:
        raise ValueError(f"case {case.get('id')!r} has no fixed criteria")
    ids = [str(entry.get("id") or "") for entry in criteria if isinstance(entry, dict)]
    if len(ids) != len(criteria) or any(not item for item in ids):
        raise ValueError(f"case {case.get('id')!r} has an invalid fixed rubric")
    return ids


def _load_cases(path: Path, requested_ids: list[str] | None = None) -> list[dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    cases = raw.get("cases") if isinstance(raw, dict) else raw
    if not isinstance(cases, list) or not cases:
        raise ValueError(f"{path}: expected a non-empty cases list")

    by_id: dict[str, dict[str, Any]] = {}
    for row in cases:
        if not isinstance(row, dict) or not str(row.get("id") or "").strip():
            raise ValueError(f"{path}: every case must be an object with a non-empty id")
        case_id = str(row["id"])
        if case_id in by_id:
            raise ValueError(f"{path}: duplicate case id {case_id!r}")
        _criterion_ids(row)
        by_id[case_id] = row

    selected_ids = requested_ids or list(DEFAULT_CASE_IDS)
    missing = [case_id for case_id in selected_ids if case_id not in by_id]
    if missing:
        raise ValueError(f"{path}: unknown case id(s): {', '.join(missing)}")
    return [by_id[case_id] for case_id in selected_ids]


def _invoke_case(
    *,
    runner: Path,
    skills_root: Path,
    case: dict[str, Any],
    timeout: int,
) -> dict[str, Any]:
    payload = {
        "schema_version": 2,
        "skills_root": str(skills_root.resolve()),
        "task": case["prompt"],
        "expected_output": case["expected_output"],
    }
    started = time.monotonic()
    process = subprocess.run(
        [sys.executable, str(runner.resolve())],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    duration_ms = round((time.monotonic() - started) * 1000)
    stdout = process.stdout.strip()
    if process.stderr.strip():
        print(process.stderr.strip()[:4000], file=sys.stderr)

    try:
        result = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"fixed-rubric runner returned invalid JSON for {case['id']}: {stdout[:500]}"
        ) from exc
    if not isinstance(result, dict):
        raise RuntimeError(f"fixed-rubric runner returned a non-object for {case['id']}")
    if process.returncode and "runner_error" not in result:
        raise RuntimeError(
            f"fixed-rubric runner exited {process.returncode} for {case['id']}: {stdout[:500]}"
        )
    result.setdefault("duration_ms", duration_ms)
    return result


def _grade_case(case: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    expected_skill = case.get("expected_skill")
    selected_skill = result.get("selected_skill")
    forbidden = set(case.get("forbidden_skills") or [])
    expected_ids = _criterion_ids(case)
    reasons: list[str] = []

    if "runner_error" in result:
        error = result.get("runner_error")
        code = error.get("code") if isinstance(error, dict) else "unknown"
        reasons.append(f"runner error: {code}")
    if selected_skill != expected_skill:
        reasons.append(f"selected {selected_skill!r}; expected {expected_skill!r}")
    if selected_skill in forbidden:
        reasons.append(f"forbidden skill collision: {selected_skill!r}")
    if result.get("task_success") is not True:
        reasons.append("host-computed task_success is not true")
    if result.get("grader_contract") != "fixed-jury-rubric-v2":
        reasons.append("fixed-jury-rubric-v2 grader contract is missing")
    if result.get("criterion_ids") != expected_ids:
        reasons.append("returned criterion IDs do not match the frozen case rubric")
    violations = result.get("grader_contract_violations")
    if violations:
        reasons.append("fixed rubric contract violation")

    assertions = result.get("assertion_results")
    if not isinstance(assertions, dict) or list(assertions) != expected_ids:
        reasons.append("assertion results are not keyed by the exact ordered criterion IDs")
    elif any(value is not True for value in assertions.values()):
        reasons.append("one or more fixed behavioral criteria failed")

    return {
        "case_id": case["id"],
        "expected_skill": expected_skill,
        "selected_skill": selected_skill,
        "passed": not reasons,
        "reasons": reasons,
        "criterion_ids": expected_ids,
        "assertion_results": assertions if isinstance(assertions, dict) else {},
        "judge_rationale": result.get("judge_rationale"),
        "duration_ms": result.get("duration_ms"),
        "runner_error": result.get("runner_error"),
    }


def run_calibration(
    *,
    cases: list[dict[str, Any]],
    skills_root: Path,
    runner: Path,
    timeout: int,
    invoke: Callable[..., dict[str, Any]] = _invoke_case,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    details: list[dict[str, Any]] = []
    grades: list[dict[str, Any]] = []
    for index, case in enumerate(cases, 1):
        print(f"[{index}/{len(cases)}] {case['id']}", file=sys.stderr)
        result = invoke(
            runner=runner,
            skills_root=skills_root,
            case=case,
            timeout=timeout,
        )
        grade = _grade_case(case, result)
        details.append({"case": case, "result": result, "grade": grade})
        grades.append(grade)

    failures = [grade for grade in grades if not grade["passed"]]
    summary = {
        "schema_version": 2,
        "kind": "provisional-balanced-single-corpus-calibration",
        "gate5_evidence": False,
        "rubric_contract": "fixed-jury-rubric-v2",
        "model": (os.environ.get("PI_EVAL_MODEL") or "").strip() or None,
        "thinking": (os.environ.get("PI_EVAL_THINKING") or "").strip() or None,
        "case_count": len(cases),
        "expected_model_calls": len(cases) * 2,
        "passed_cases": len(cases) - len(failures),
        "failed_cases": len(failures),
        "all_passed": not failures,
        "cases": grades,
        "next_gate_requirement": (
            "A new byte-identical A/A run under suite v3 and fixed-jury-rubric-v2, "
            "followed by two passing blinded A/B rounds."
        ),
    }
    return summary, details


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skills-root", type=Path, default=DEFAULT_SKILLS)
    parser.add_argument("--evals", type=Path, default=DEFAULT_EVALS)
    parser.add_argument(
        "--case",
        dest="case_ids",
        action="append",
        help="case id to run; repeat for multiple cases (default: balanced five-case set)",
    )
    parser.add_argument("--runner", type=Path, default=DEFAULT_RUNNER)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--timeout", type=int, default=600)
    args = parser.parse_args(argv)

    if not (os.environ.get("PI_EVAL_MODEL") or "").strip():
        parser.error("PI_EVAL_MODEL must be pinned before calibration")
    if not args.skills_root.is_dir():
        parser.error(f"skills root does not exist: {args.skills_root}")
    if not args.runner.is_file():
        parser.error(f"fixed-rubric runner does not exist: {args.runner}")
    if args.timeout < 1:
        parser.error("--timeout must be positive")

    try:
        cases = _load_cases(args.evals, args.case_ids)
        summary, details = run_calibration(
            cases=cases,
            skills_root=args.skills_root,
            runner=args.runner,
            timeout=args.timeout,
        )
    except Exception as exc:  # noqa: BLE001 - one actionable local failure
        print(
            json.dumps(
                {
                    "runner_error": {
                        "code": "calibration_failure",
                        "message": str(exc)[:500],
                    }
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )
        return 2

    args.out.parent.mkdir(parents=True, exist_ok=True)
    report = {**summary, "details": details}
    args.out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    summary["report_path"] = str(args.out)
    print(json.dumps(summary, ensure_ascii=False, separators=(",", ":")))
    return 0 if summary["all_passed"] else 5


if __name__ == "__main__":
    raise SystemExit(main())
