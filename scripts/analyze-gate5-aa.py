#!/usr/bin/env python3
"""Diagnose a completed Gate 5 A/A run without making model calls.

The A/A corpora are byte-identical, so the labels named ``candidate`` and
``baseline`` are arbitrary arms. This tool pairs observations by case and
repetition, identifies routing and task-success disagreements, and writes a
small review queue containing assertion failures, judge rationales, and bounded
response excerpts. It never invokes Pi and never accesses PROCESIO.
"""
from __future__ import annotations

import argparse
import json
import math
import re
from collections import defaultdict
from pathlib import Path
from typing import Any


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return value


def _load_rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise FileNotFoundError(path)
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_number}: invalid JSON") from exc
        if not isinstance(value, dict):
            raise ValueError(f"{path}:{line_number}: expected an object")
        rows.append(value)
    return rows


def _response_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _excerpt(value: Any, limit: int) -> str:
    text = re.sub(r"\s+", " ", _response_text(value)).strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def _false_assertions(row: dict[str, Any]) -> list[str]:
    assertions = row.get("assertion_results")
    if not isinstance(assertions, dict):
        return ["<missing-assertion-results>"]
    return sorted(str(key) for key, value in assertions.items() if value is not True)


def _exact_two_sided_sign_test(left_only: int, right_only: int) -> float:
    """Two-sided exact sign test over discordant pairs.

    This is diagnostic only. It does not replace the pre-registered A/A gate.
    """
    discordant = left_only + right_only
    if discordant == 0:
        return 1.0
    lower = min(left_only, right_only)
    tail = sum(math.comb(discordant, index) for index in range(lower + 1))
    return min(1.0, 2.0 * tail / (2**discordant))


def analyze_run(run_root: Path, *, response_chars: int = 700) -> dict[str, Any]:
    run_root = run_root.expanduser().resolve()
    results = run_root / "results"
    report = _load_json(results / "report.json")
    rows = _load_rows(results / "runs.jsonl")

    if report.get("mode") != "aa":
        raise ValueError(f"{results / 'report.json'}: expected mode 'aa'")
    labels = report.get("blind_label_mapping")
    if not isinstance(labels, dict) or set(labels.values()) != {"candidate", "baseline"}:
        raise ValueError("report has no valid two-arm blind_label_mapping")
    if report.get("candidate_fingerprint") != report.get("baseline_fingerprint"):
        raise ValueError("A/A report fingerprints are not byte-identical")

    expected_total = int(report.get("case_count") or 0) * int(report.get("repetitions") or 0) * 2
    if expected_total and len(rows) != expected_total:
        raise ValueError(f"checkpoint has {len(rows)} rows; complete report expects {expected_total}")

    pairs: dict[tuple[str, int], dict[str, dict[str, Any]]] = defaultdict(dict)
    arm_rows: dict[str, list[dict[str, Any]]] = {"candidate": [], "baseline": []}
    for row in rows:
        try:
            case_id = str(row["case_id"])
            repetition = int(row["repetition"])
            variant_label = str(row["variant_label"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("one or more rows have no valid case/repetition/label identity") from exc
        if variant_label not in labels:
            raise ValueError(f"unknown variant label: {variant_label!r}")
        arm = str(labels[variant_label])
        if arm in pairs[(case_id, repetition)]:
            raise ValueError(f"duplicate pair arm for {(case_id, repetition, arm)}")
        pairs[(case_id, repetition)][arm] = row
        arm_rows[arm].append(row)

    incomplete = [key for key, pair in pairs.items() if set(pair) != {"candidate", "baseline"}]
    if incomplete:
        raise ValueError(f"incomplete A/A pairs: {incomplete[:5]}")

    per_case: dict[str, dict[str, Any]] = {}
    review_queue: list[dict[str, Any]] = []
    candidate_only_passes = 0
    baseline_only_passes = 0
    both_pass = 0
    both_fail = 0
    selection_disagreements = 0
    response_exact_matches = 0

    for (case_id, repetition), pair in sorted(pairs.items()):
        candidate = pair["candidate"]
        baseline = pair["baseline"]
        candidate_success = candidate.get("task_success") is True
        baseline_success = baseline.get("task_success") is True
        same_selection = candidate.get("selected_skill") == baseline.get("selected_skill")
        same_response = _response_text(candidate.get("response")) == _response_text(
            baseline.get("response")
        )
        if not same_selection:
            selection_disagreements += 1
        if same_response:
            response_exact_matches += 1

        case = per_case.setdefault(
            case_id,
            {
                "case_id": case_id,
                "pairs": 0,
                "candidate_passes": 0,
                "baseline_passes": 0,
                "both_pass": 0,
                "both_fail": 0,
                "task_success_disagreements": 0,
                "selection_disagreements": 0,
            },
        )
        case["pairs"] += 1
        case["candidate_passes"] += int(candidate_success)
        case["baseline_passes"] += int(baseline_success)
        case["selection_disagreements"] += int(not same_selection)

        if candidate_success and baseline_success:
            both_pass += 1
            case["both_pass"] += 1
        elif not candidate_success and not baseline_success:
            both_fail += 1
            case["both_fail"] += 1
        else:
            case["task_success_disagreements"] += 1
            if candidate_success:
                candidate_only_passes += 1
            else:
                baseline_only_passes += 1

        if (candidate_success != baseline_success) or not same_selection or not candidate_success or not baseline_success:
            arms: dict[str, Any] = {}
            for arm, row in (("candidate", candidate), ("baseline", baseline)):
                arms[arm] = {
                    "task_success": row.get("task_success") is True,
                    "selected_skill": row.get("selected_skill"),
                    "expected_skill": row.get("expected_skill"),
                    "false_assertions": _false_assertions(row),
                    "assertion_results": row.get("assertion_results"),
                    "judge_rationale": str(row.get("judge_rationale") or "")[:1200],
                    "response_excerpt": _excerpt(row.get("response"), response_chars),
                }
            review_queue.append(
                {
                    "case_id": case_id,
                    "repetition": repetition + 1,
                    "same_selected_skill": same_selection,
                    "same_response_text": same_response,
                    "arms": arms,
                }
            )

    arm_summary: dict[str, Any] = {}
    for arm in ("candidate", "baseline"):
        items = arm_rows[arm]
        arm_summary[arm] = {
            "runs": len(items),
            "selection_passes": sum(
                row.get("selected_skill") == row.get("expected_skill") for row in items
            ),
            "task_successes": sum(row.get("task_success") is True for row in items),
            "task_failures": sum(row.get("task_success") is not True for row in items),
            "collisions": sum(
                row.get("selected_skill") in set(row.get("forbidden_skills") or [])
                for row in items
            ),
        }

    task_success_disagreements = candidate_only_passes + baseline_only_passes
    gate = report.get("gate") if isinstance(report.get("gate"), dict) else {}
    conclusion = (
        "Routing is stable; the response-plus-judge task-success pipeline exceeded the registered A/A noise limit."
        if selection_disagreements == 0 and task_success_disagreements
        else "The A/A run contains routing and/or task-success variance requiring review."
    )
    return {
        "schema_version": 1,
        "kind": "gate5-aa-diagnostic",
        "run_root": str(run_root),
        "mode": "aa",
        "byte_identical_corpora": True,
        "labels_are_semantically_arbitrary": True,
        "gate": gate,
        "arm_summary": arm_summary,
        "paired_summary": {
            "pairs": len(pairs),
            "both_pass": both_pass,
            "both_fail": both_fail,
            "candidate_only_passes": candidate_only_passes,
            "baseline_only_passes": baseline_only_passes,
            "task_success_disagreements": task_success_disagreements,
            "selection_disagreements": selection_disagreements,
            "response_exact_matches": response_exact_matches,
            "discordant_pair_exact_sign_test_p": _exact_two_sided_sign_test(
                candidate_only_passes, baseline_only_passes
            ),
            "sign_test_is_diagnostic_not_gate_override": True,
        },
        "per_case": sorted(per_case.values(), key=lambda item: item["case_id"]),
        "review_queue": review_queue,
        "conclusion": conclusion,
        "next_decision": (
            "Review the discordant and failed rows. Do not loosen thresholds or start A/B. "
            "If satisfactory responses were graded inconsistently, version and stabilize the judge contract; "
            "if responses genuinely omitted criteria, retune the relevant skill or evaluation case. Then start a new A/A run."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_root", type=Path)
    parser.add_argument("--response-chars", type=int, default=700)
    parser.add_argument(
        "--out",
        type=Path,
        help="output path; defaults to <run_root>/results/aa-diagnostic.json",
    )
    parser.add_argument("--print-full", action="store_true")
    args = parser.parse_args(argv)
    if args.response_chars < 80:
        parser.error("--response-chars must be at least 80")

    try:
        result = analyze_run(args.run_root, response_chars=args.response_chars)
    except Exception as exc:  # noqa: BLE001 - one safe machine-readable failure
        print(
            json.dumps(
                {
                    "runner_error": {
                        "code": "aa_diagnostic_failed",
                        "message": str(exc)[:800],
                    }
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )
        return 2

    out = args.out or args.run_root.expanduser().resolve() / "results" / "aa-diagnostic.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    if args.print_full:
        printable = result
    else:
        printable = {
            "schema_version": result["schema_version"],
            "kind": result["kind"],
            "gate": result["gate"],
            "arm_summary": result["arm_summary"],
            "paired_summary": result["paired_summary"],
            "per_case": result["per_case"],
            "review_queue": result["review_queue"],
            "conclusion": result["conclusion"],
            "next_decision": result["next_decision"],
            "diagnostic_path": str(out),
        }
    print(json.dumps(printable, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
