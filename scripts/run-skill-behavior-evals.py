#!/usr/bin/env python3
"""Run paired, blinded skill-corpus evaluations through an external model runner.

The runner is provider-neutral. It receives one JSON object on stdin and must
return one JSON object on stdout. Run ``--mode aa`` against two identical
checkouts first, then ``--mode ab`` against old and candidate corpora with the
same command, cases, repetitions, and controlled seeds.

Runs are checkpointed after every completed observation. ``--resume`` reuses the
same deterministic job order and skips completed observations. A structured
runner error (for example model quota exhaustion) produces a resumable partial
report instead of discarding completed work.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import shlex
import statistics
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVALS = ROOT / "skills" / "evals" / "behavioral.json"
DEFAULT_THRESHOLDS = ROOT / "skills" / "evals" / "gate5-thresholds.json"
INCOMPLETE_EXIT = 75


class RunnerInvocationError(RuntimeError):
    """A runner stopped safely and returned a structured error object."""

    def __init__(
        self,
        result: dict[str, Any],
        *,
        stderr: str,
        duration_ms: int,
        returncode: int,
    ) -> None:
        error = result.get("runner_error")
        message = (
            str(error.get("message"))
            if isinstance(error, dict) and error.get("message")
            else f"runner exited {returncode}"
        )
        super().__init__(message)
        self.result = result
        self.stderr = stderr
        self.duration_ms = duration_ms
        self.returncode = returncode


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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


def _split_runner(value: str, *, platform: str | None = None) -> list[str]:
    """Split an argv command without corrupting Windows backslash paths."""
    platform = os.name if platform is None else platform
    if platform != "nt":
        return shlex.split(value)
    tokens = shlex.split(value, posix=False)
    cleaned: list[str] = []
    for token in tokens:
        if len(token) >= 2 and token[0] == token[-1] and token[0] in {'"', "'"}:
            token = token[1:-1]
        cleaned.append(token)
    return cleaned


def _parse_single_json_object(stdout: str) -> dict[str, Any]:
    lines = [line for line in stdout.splitlines() if line.strip()]
    if len(lines) != 1:
        raise RuntimeError("runner must print exactly one JSON object on stdout")
    try:
        result = json.loads(lines[0])
    except json.JSONDecodeError as exc:
        raise RuntimeError("runner stdout is not valid JSON") from exc
    if not isinstance(result, dict):
        raise RuntimeError("runner output must be a JSON object")
    return result


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
    stdout = proc.stdout.strip()
    stderr = proc.stderr.strip()

    result: dict[str, Any] | None = None
    if stdout:
        try:
            result = _parse_single_json_object(stdout)
        except RuntimeError:
            if proc.returncode == 0:
                raise

    if result is not None and "runner_error" in result:
        raise RunnerInvocationError(
            result,
            stderr=stderr,
            duration_ms=duration_ms,
            returncode=proc.returncode,
        )
    if proc.returncode:
        raise RuntimeError(
            f"runner exited {proc.returncode}: {stderr or stdout or 'no diagnostic output'}"
        )
    if result is None:
        result = _parse_single_json_object(stdout)

    result.setdefault("duration_ms", duration_ms)
    result["runner_stderr"] = stderr
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
        label = row.get("variant_label")
        if label not in labels:
            raise ValueError(f"unknown variant label in checkpoint: {label!r}")
        by_variant[labels[str(label)]].append(row)
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


def _gate(
    summary: dict[str, Any],
    thresholds: dict[str, Any],
    repetitions: int,
    provisional: bool,
    mode: str = "ab",
) -> dict[str, Any]:
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


def _planned_experiment(
    *,
    cases: list[dict[str, Any]],
    repetitions: int,
    seed: int,
    candidate_root: Path,
    baseline_root: Path,
) -> tuple[list[str], dict[str, str], dict[str, Path], list[tuple[dict[str, Any], int, str]]]:
    rng = random.Random(seed)
    labels_list = ["corpus-a", "corpus-b"]
    rng.shuffle(labels_list)
    labels = {labels_list[0]: "candidate", labels_list[1]: "baseline"}
    roots = {
        labels_list[0]: candidate_root.resolve(),
        labels_list[1]: baseline_root.resolve(),
    }
    jobs = [
        (case, repetition, label)
        for repetition in range(repetitions)
        for case in cases
        for label in labels_list
    ]
    rng.shuffle(jobs)
    return labels_list, labels, roots, jobs


def _job_key(case_id: str, repetition: int, label: str) -> tuple[str, int, str]:
    return case_id, repetition, label


def _load_checkpoint(
    path: Path,
    *,
    planned_keys: set[tuple[str, int, str]],
) -> tuple[list[dict[str, Any]], set[tuple[str, int, str]]]:
    if not path.is_file():
        return [], set()
    rows: list[dict[str, Any]] = []
    completed: set[tuple[str, int, str]] = set()
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_number}: invalid checkpoint JSON") from exc
        if not isinstance(row, dict):
            raise ValueError(f"{path}:{line_number}: checkpoint row must be an object")
        try:
            key = _job_key(
                str(row["case_id"]),
                int(row["repetition"]),
                str(row["variant_label"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"{path}:{line_number}: checkpoint row has no valid job identity") from exc
        if key not in planned_keys:
            raise ValueError(f"{path}:{line_number}: checkpoint job is not in this experiment: {key}")
        if key in completed:
            raise ValueError(f"{path}:{line_number}: duplicate checkpoint job: {key}")
        completed.add(key)
        rows.append(row)
    return rows, completed


def _runner_environment() -> dict[str, str | None]:
    names = (
        "PI_EVAL_MODEL",
        "PI_EVAL_PROVIDER",
        "PI_EVAL_THINKING",
        "PI_EVAL_CALL_TIMEOUT",
    )
    return {name: os.environ.get(name) for name in names}


def _experiment_manifest(
    *,
    mode: str,
    seed: int,
    repetitions: int,
    cases: list[dict[str, Any]],
    labels: dict[str, str],
    command: list[str],
    candidate_fingerprint: str,
    baseline_fingerprint: str,
    evals_path: Path,
    thresholds_path: Path,
    provisional: bool,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "mode": mode,
        "seed": seed,
        "repetitions": repetitions,
        "case_ids": [str(case["id"]) for case in cases],
        "total_observations": len(cases) * repetitions * 2,
        "blind_label_mapping": labels,
        "candidate_fingerprint": candidate_fingerprint,
        "baseline_fingerprint": baseline_fingerprint,
        "evals_sha256": _sha256_file(evals_path),
        "thresholds_sha256": _sha256_file(thresholds_path),
        "runner_command": command,
        "runner_environment": _runner_environment(),
        "provisional": provisional,
    }


def _validate_or_write_manifest(
    path: Path,
    expected: dict[str, Any],
    *,
    resume: bool,
    existing_rows: int,
) -> dict[str, Any]:
    if path.is_file():
        actual = _load_json(path)
        if not isinstance(actual, dict):
            raise ValueError(f"{path}: expected an object")
        for key, value in expected.items():
            if key == "created_at":
                continue
            if actual.get(key) != value:
                raise ValueError(
                    f"cannot resume: experiment setting {key!r} changed "
                    f"from {actual.get(key)!r} to {value!r}"
                )
        return actual

    if existing_rows and not resume:
        raise ValueError("checkpoint exists but --resume was not supplied")
    manifest = {
        **expected,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "adopted_existing_checkpoint": bool(existing_rows),
        "adopted_observations": existing_rows,
    }
    _write_json(path, manifest)
    return manifest


def _partial_report(
    *,
    status: str,
    rows: list[dict[str, Any]],
    total: int,
    labels: dict[str, str],
    manifest: dict[str, Any],
    interruption: dict[str, Any] | None = None,
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "schema_version": 1,
        "status": status,
        "resumable": True,
        "completed_observations": len(rows),
        "total_observations": total,
        "remaining_observations": total - len(rows),
        "partial_summary": _summary(rows, labels),
        "experiment": manifest,
    }
    if interruption is not None:
        report["interruption"] = interruption
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--baseline-root", type=Path, required=True)
    parser.add_argument("--evals", type=Path, default=DEFAULT_EVALS)
    parser.add_argument("--thresholds", type=Path, default=DEFAULT_THRESHOLDS)
    parser.add_argument(
        "--runner",
        required=True,
        help="command that reads one JSON request and writes one JSON result",
    )
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--repetitions", type=int, default=5)
    parser.add_argument("--seed", type=int, default=20260903)
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--mode", choices=("aa", "ab"), default="ab")
    parser.add_argument("--provisional", action="store_true")
    parser.add_argument(
        "--resume",
        action="store_true",
        help="append to an existing compatible runs.jsonl checkpoint",
    )
    parser.add_argument(
        "--max-new-observations",
        type=int,
        help="stop cleanly after at most this many newly completed observations",
    )
    args = parser.parse_args(argv)

    if args.repetitions < 1:
        parser.error("--repetitions must be >= 1")
    if args.timeout < 1:
        parser.error("--timeout must be positive")
    if args.max_new_observations is not None and args.max_new_observations < 1:
        parser.error("--max-new-observations must be >= 1")
    for root in (args.candidate_root, args.baseline_root):
        if not root.is_dir():
            parser.error(f"skill root does not exist: {root}")
    for path in (args.evals, args.thresholds):
        if not path.is_file():
            parser.error(f"required file does not exist: {path}")

    candidate_fingerprint = _fingerprint(args.candidate_root)
    baseline_fingerprint = _fingerprint(args.baseline_root)
    if args.mode == "aa" and candidate_fingerprint != baseline_fingerprint:
        parser.error("--mode aa requires byte-identical skill corpora")

    cases = _cases(args.evals)
    thresholds = _load_json(args.thresholds)
    if not isinstance(thresholds, dict):
        parser.error("thresholds file must contain a JSON object")
    command = _split_runner(args.runner)
    if not command:
        parser.error("--runner is empty")

    _labels_list, labels, roots, jobs = _planned_experiment(
        cases=cases,
        repetitions=args.repetitions,
        seed=args.seed,
        candidate_root=args.candidate_root,
        baseline_root=args.baseline_root,
    )
    planned_keys = {
        _job_key(str(case["id"]), repetition, label)
        for case, repetition, label in jobs
    }

    args.workspace.mkdir(parents=True, exist_ok=True)
    runs_path = args.workspace / "runs.jsonl"
    if runs_path.exists() and not args.resume:
        parser.error(
            f"checkpoint already exists at {runs_path}; use --resume or a new workspace"
        )
    rows, completed = _load_checkpoint(runs_path, planned_keys=planned_keys)

    manifest_expected = _experiment_manifest(
        mode=args.mode,
        seed=args.seed,
        repetitions=args.repetitions,
        cases=cases,
        labels=labels,
        command=command,
        candidate_fingerprint=candidate_fingerprint,
        baseline_fingerprint=baseline_fingerprint,
        evals_path=args.evals,
        thresholds_path=args.thresholds,
        provisional=args.provisional,
    )
    manifest = _validate_or_write_manifest(
        args.workspace / "experiment.json",
        manifest_expected,
        resume=args.resume,
        existing_rows=len(rows),
    )

    total = len(jobs)
    new_limit = args.max_new_observations
    new_completed = 0
    mode = "a" if runs_path.exists() else "w"
    with runs_path.open(mode, encoding="utf-8") as stream:
        for sequence, (case, repetition, label) in enumerate(jobs, 1):
            key = _job_key(str(case["id"]), repetition, label)
            if key in completed:
                continue
            if new_limit is not None and new_completed >= new_limit:
                break

            run_id = f"{case['id']}-{repetition}-{label}"
            payload = {
                "schema_version": 1,
                "run_id": run_id,
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
            try:
                result = _run(command, payload, args.timeout)
            except RunnerInvocationError as exc:
                interruption = {
                    "run_id": run_id,
                    "sequence": sequence,
                    "runner_error": exc.result.get("runner_error"),
                    "runner_exit_code": exc.returncode,
                    "duration_ms": exc.duration_ms,
                    "runner_stderr": exc.stderr,
                    "observed_at": datetime.now(timezone.utc).isoformat(),
                }
                partial = _partial_report(
                    status="interrupted",
                    rows=rows,
                    total=total,
                    labels=labels,
                    manifest=manifest,
                    interruption=interruption,
                )
                _write_json(args.workspace / "interruption.json", interruption)
                _write_json(args.workspace / "partial-report.json", partial)
                print(json.dumps(partial, ensure_ascii=False, separators=(",", ":")))
                return INCOMPLETE_EXIT

            row = {
                "sequence": sequence,
                "run_id": run_id,
                "case_id": case["id"],
                "repetition": repetition,
                "variant_label": label,
                "expected_skill": case.get("expected_skill"),
                "forbidden_skills": case.get("forbidden_skills") or [],
                **result,
            }
            rows.append(row)
            completed.add(key)
            new_completed += 1
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
            stream.flush()

    if len(rows) < total:
        partial = _partial_report(
            status="paused",
            rows=rows,
            total=total,
            labels=labels,
            manifest=manifest,
        )
        _write_json(args.workspace / "partial-report.json", partial)
        print(json.dumps(partial, ensure_ascii=False, separators=(",", ":")))
        return INCOMPLETE_EXIT

    summary = _summary(rows, labels)
    report = {
        "schema_version": 1,
        "status": "complete",
        "mode": args.mode,
        "seed": args.seed,
        "repetitions": args.repetitions,
        "case_count": len(cases),
        "blind_label_mapping": labels,
        "candidate_fingerprint": candidate_fingerprint,
        "baseline_fingerprint": baseline_fingerprint,
        "summary": summary,
        "gate": _gate(summary, thresholds, args.repetitions, args.provisional, args.mode),
    }
    _write_json(args.workspace / "report.json", report)
    for stale in (args.workspace / "partial-report.json", args.workspace / "interruption.json"):
        if stale.exists():
            stale.unlink()
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["gate"]["passed"] else 5


if __name__ == "__main__":
    raise SystemExit(main())
