#!/usr/bin/env python3
"""Run paired, blinded skill-corpus evaluations through an external model runner.

The runner is provider-neutral. It receives one JSON object on stdin and must
return one JSON object on stdout. Run ``--mode aa`` against two identical
checkouts first, then ``--mode ab`` against old and candidate corpora with the
same command, cases, repetitions, and controlled seeds.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import shlex
import statistics
import subprocess
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVALS = ROOT / "skills" / "evals" / "behavioral.json"
DEFAULT_THRESHOLDS = ROOT / "skills" / "evals" / "gate5-thresholds.json"


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _cases(path: Path) -> list[dict[str, Any]]:
    raw = _load_json(path)
    rows = raw.get("cases") if isinstance(raw, dict) else raw
    if not isinstance(rows, list) or not rows:
        raise ValueError(f"{path}: expected a non-empty cases list")
    ids = [str(row.get("id") or "") for row in rows]
    if any(not item for item in ids) or len(ids) != len(set(ids)):
        raise ValueError(f"{path}: case ids must be non-empty and unique")
    return rows


def _fingerprint(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _run(command: list[str], payload: dict[str, Any], timeout: int) -> dict[str, Any]:
    started = time.monotonic()
    proc = subprocess.run(
        command,
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    duration_ms = round((time.monotonic() - started) * 1000)
    if proc.returncode:
        raise RuntimeError(
            f"runner exited {proc.returncode}: {proc.stderr.strip() or proc.stdout.strip()}"
        )
    lines = [line for line in proc.stdout.splitlines() if line.strip()]
    if len(lines) != 1:
        raise RuntimeError("runner must print exactly one JSON object on stdout")
    result = json.loads(lines[0])
    if not isinstance(result, dict):
        raise RuntimeError("runner output must be a JSON object")
    result.setdefault("duration_ms", duration_ms)
    result["runner_stderr"] = proc.stderr.strip()
    return result


def _metric(rows: list[dict[str, Any]], field: str) -> dict[str, float | int | None]:
    values = [float(row[field]) for row in rows if row.get(field) is not None]
    return {
        "count": len(values),
        "mean": statistics.mean(values) if values else None,
        "stddev": statistics.pstdev(values) if len(values) > 1 else 0.0 if values else None,
    }


def _summary(rows: list[dict[str, Any]], labels: dict[str, str]) -> dict[str, Any]:
    by_variant: dict[str, list[dict[str, Any]]] = {"candidate": [], "baseline": []}
    for row in rows:
        by_variant[labels[row["variant_label"]]].append(row)
    out: dict[str, Any] = {}
    for variant, items in by_variant.items():
        selection = [int(row.get("selected_skill") == row.get("expected_skill")) for row in items]
        success = [int(bool(row.get("task_success"))) for row in items]
        collisions = [
            int(row.get("selected_skill") in set(row.get("forbidden_skills") or []))
            for row in items
        ]
        out[variant] = {
            "runs": len(items),
            "selection_accuracy": statistics.mean(selection) if selection else None,
            "task_success_rate": statistics.mean(success) if success else None,
            "collision_rate": statistics.mean(collisions) if collisions else None,
            "tokens": _metric(items, "total_tokens"),
            "duration_ms": _metric(items, "duration_ms"),
        }
    for metric in ("selection_accuracy", "task_success_rate", "collision_rate"):
        candidate = out["candidate"][metric]
        baseline = out["baseline"][metric]
        out[f"{metric}_delta"] = (
            candidate - baseline if candidate is not None and baseline is not None else None
        )
    return out


def _gate(summary: dict[str, Any], thresholds: dict[str, Any], repetitions: int,
          provisional: bool, mode: str = "ab") -> dict[str, Any]:
    candidate = summary["candidate"]
    reasons: list[str] = []
    minimum_repetitions = int(thresholds.get("minimum_repetitions", 5))
    if repetitions < minimum_repetitions:
        reasons.append(f"{repetitions} repetitions < required {minimum_repetitions}")

    if mode == "aa":
        limits = {
            "selection_accuracy_delta": float(thresholds.get("max_aa_selection_delta", 0.05)),
            "task_success_rate_delta": float(thresholds.get("max_aa_task_success_delta", 0.05)),
            "collision_rate_delta": float(thresholds.get("max_aa_collision_delta", 0.02)),
        }
        for field, limit in limits.items():
            value = summary.get(field)
            if value is None or abs(float(value)) > limit:
                reasons.append(f"A/A {field} exceeds noise limit {limit}")
    else:
        if candidate["selection_accuracy"] < float(
            thresholds.get("min_selection_accuracy", 0.92)
        ):
            reasons.append("selection accuracy below threshold")
        if candidate["collision_rate"] > float(thresholds.get("max_collision_rate", 0.0)):
            reasons.append("collision rate above threshold")
        required_delta = float(thresholds.get("min_task_success_delta", 0.15))
        if summary["task_success_rate_delta"] < required_delta:
            reasons.append("task-success improvement below threshold")

    passed = not reasons and not provisional
    if provisional:
        reasons.append("run explicitly marked provisional")
    return {"passed": passed, "mode": mode, "reasons": reasons}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--baseline-root", type=Path, required=True)
    parser.add_argument("--evals", type=Path, default=DEFAULT_EVALS)
    parser.add_argument("--thresholds", type=Path, default=DEFAULT_THRESHOLDS)
    parser.add_argument("--runner", required=True,
                        help="command that reads one JSON request and writes one JSON result")
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--repetitions", type=int, default=5)
    parser.add_argument("--seed", type=int, default=20260903)
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--mode", choices=("aa", "ab"), default="ab")
    parser.add_argument("--provisional", action="store_true")
    args = parser.parse_args(argv)

    if args.repetitions < 1:
        parser.error("--repetitions must be >= 1")
    for root in (args.candidate_root, args.baseline_root):
        if not root.is_dir():
            parser.error(f"skill root does not exist: {root}")

    candidate_fingerprint = _fingerprint(args.candidate_root)
    baseline_fingerprint = _fingerprint(args.baseline_root)
    if args.mode == "aa" and candidate_fingerprint != baseline_fingerprint:
        parser.error("--mode aa requires byte-identical skill corpora")

    cases = _cases(args.evals)
    thresholds = _load_json(args.thresholds)
    command = shlex.split(args.runner)
    if not command:
        parser.error("--runner is empty")
    rng = random.Random(args.seed)
    labels_list = ["corpus-a", "corpus-b"]
    rng.shuffle(labels_list)
    labels = {labels_list[0]: "candidate", labels_list[1]: "baseline"}
    roots = {labels_list[0]: args.candidate_root.resolve(),
             labels_list[1]: args.baseline_root.resolve()}

    jobs = [
        (case, repetition, label)
        for repetition in range(args.repetitions)
        for case in cases
        for label in labels_list
    ]
    rng.shuffle(jobs)
    rows: list[dict[str, Any]] = []
    args.workspace.mkdir(parents=True, exist_ok=True)
    runs_path = args.workspace / "runs.jsonl"
    with runs_path.open("w", encoding="utf-8") as stream:
        for index, (case, repetition, label) in enumerate(jobs, 1):
            payload = {
                "schema_version": 1,
                "run_id": f"{case['id']}-{repetition}-{label}",
                "variant_label": label,
                "skills_root": str(roots[label]),
                "task": case["prompt"],
                "expected_output": case.get("expected_output"),
                "output_contract": {
                    "selected_skill": "string or null",
                    "task_success": "boolean",
                    "response": "string or JSON object",
                    "assertion_results": "optional object of assertion -> boolean",
                    "total_tokens": "optional integer",
                },
            }
            result = _run(command, payload, args.timeout)
            row = {
                "sequence": index,
                "case_id": case["id"],
                "repetition": repetition,
                "variant_label": label,
                "expected_skill": case.get("expected_skill"),
                "forbidden_skills": case.get("forbidden_skills") or [],
                **result,
            }
            rows.append(row)
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
            stream.flush()

    summary = _summary(rows, labels)
    report = {
        "schema_version": 1,
        "mode": args.mode,
        "seed": args.seed,
        "repetitions": args.repetitions,
        "case_count": len(cases),
        "blind_label_mapping": labels,
        "candidate_fingerprint": candidate_fingerprint,
        "baseline_fingerprint": baseline_fingerprint,
        "summary": summary,
        "gate": _gate(summary, thresholds, args.repetitions,
                      args.provisional, args.mode),
    }
    (args.workspace / "report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["gate"]["passed"] else 5


if __name__ == "__main__":
    raise SystemExit(main())
