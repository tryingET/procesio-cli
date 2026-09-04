#!/usr/bin/env python3
"""Run the formal local Pi Gate 5 A/A noise-floor experiment.

This helper deliberately performs only the first formal Gate 5 phase. It copies
one current skill corpus into two independent directories, invokes the existing
paired behavioral harness in A/A mode, shows observation progress, and emits one
compact summary. It never accesses PROCESIO.
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "skills"
BEHAVIORAL = SKILLS / "evals" / "behavioral.json"
THRESHOLDS = SKILLS / "evals" / "gate5-thresholds.json"
HARNESS = ROOT / "scripts" / "run-skill-behavior-evals.py"
STRICT_RUNNER = ROOT / "scripts" / "pi-skill-eval-runner-strict.py"


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return value


def _expected_counts(*, case_count: int, repetitions: int) -> tuple[int, int]:
    observations = case_count * repetitions * 2
    # The strict Pi adapter makes one response call and one independent judge call.
    return observations, observations * 2


def _join_argv(argv: list[str], *, platform: str | None = None) -> str:
    platform = os.name if platform is None else platform
    if platform == "nt":
        return subprocess.list2cmdline(argv)
    return shlex.join(argv)


def _copy_independent_corpora(source: Path, run_root: Path) -> tuple[Path, Path]:
    if run_root.exists():
        raise FileExistsError(
            f"run directory already exists: {run_root}. Choose a new --out-root."
        )
    run_root.mkdir(parents=True)
    corpus_a = run_root / "corpus-a"
    corpus_b = run_root / "corpus-b"
    shutil.copytree(source, corpus_a)
    shutil.copytree(source, corpus_b)
    return corpus_a, corpus_b


def _build_harness_command(
    *,
    corpus_a: Path,
    corpus_b: Path,
    results: Path,
    repetitions: int,
    seed: int,
    timeout: int,
    platform: str | None = None,
) -> list[str]:
    runner_command = _join_argv(
        [sys.executable, str(STRICT_RUNNER)], platform=platform
    )
    return [
        sys.executable,
        str(HARNESS),
        "--mode",
        "aa",
        "--candidate-root",
        str(corpus_a),
        "--baseline-root",
        str(corpus_b),
        "--evals",
        str(BEHAVIORAL),
        "--thresholds",
        str(THRESHOLDS),
        "--runner",
        runner_command,
        "--workspace",
        str(results),
        "--repetitions",
        str(repetitions),
        "--seed",
        str(seed),
        "--timeout",
        str(timeout),
    ]


def _completed_rows(path: Path) -> tuple[int, str | None]:
    if not path.is_file():
        return 0, None
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line]
    if not lines:
        return 0, None
    try:
        row = json.loads(lines[-1])
    except json.JSONDecodeError:
        return len(lines), None
    label = None
    if isinstance(row, dict):
        case_id = row.get("case_id")
        repetition = row.get("repetition")
        if case_id is not None and repetition is not None:
            label = f"{case_id}, repetition {int(repetition) + 1}"
    return len(lines), label


def _run_with_progress(command: list[str], *, results: Path, total: int) -> int:
    process = subprocess.Popen(
        command,
        cwd=ROOT,
        env=os.environ.copy(),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    runs_path = results / "runs.jsonl"
    shown = -1
    while process.poll() is None:
        completed, label = _completed_rows(runs_path)
        if completed != shown:
            suffix = f" — {label}" if label else ""
            print(f"[{completed}/{total}] observations complete{suffix}", file=sys.stderr, flush=True)
            shown = completed
        time.sleep(1)

    stdout, stderr = process.communicate()
    completed, label = _completed_rows(runs_path)
    if completed != shown:
        suffix = f" — {label}" if label else ""
        print(f"[{completed}/{total}] observations complete{suffix}", file=sys.stderr, flush=True)
    if stderr.strip():
        print(stderr.strip(), file=sys.stderr)
    if process.returncode not in (0, 5) and stdout.strip():
        print(stdout.strip(), file=sys.stderr)
    return int(process.returncode or 0)


def main(argv: list[str] | None = None) -> int:
    thresholds = _load_json(THRESHOLDS)
    behavioral = _load_json(BEHAVIORAL)
    cases = behavioral.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError(f"{BEHAVIORAL}: expected a non-empty cases list")

    minimum_repetitions = int(thresholds.get("minimum_repetitions", 5))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repetitions", type=int, default=minimum_repetitions)
    parser.add_argument("--seed", type=int, default=20260902)
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument(
        "--out-root",
        type=Path,
        help="new run directory; defaults to a timestamped directory under scratchpad",
    )
    parser.add_argument(
        "--confirm-model-calls",
        type=int,
        required=True,
        help="must equal the calculated model-call budget",
    )
    args = parser.parse_args(argv)

    model = (os.environ.get("PI_EVAL_MODEL") or "").strip()
    if not model:
        parser.error("PI_EVAL_MODEL must contain the exact provider/model ID")
    if args.repetitions < minimum_repetitions:
        parser.error(
            f"formal A/A requires at least {minimum_repetitions} repetitions"
        )
    if args.timeout < 1:
        parser.error("--timeout must be positive")

    observations, model_calls = _expected_counts(
        case_count=len(cases), repetitions=args.repetitions
    )
    if args.confirm_model_calls != model_calls:
        parser.error(
            f"--confirm-model-calls must be {model_calls} for this suite, not "
            f"{args.confirm_model_calls}"
        )

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_root = (
        args.out_root.expanduser().resolve()
        if args.out_root
        else ROOT / "scratchpad" / f"gate5-aa-v2-{timestamp}"
    )
    corpus_a, corpus_b = _copy_independent_corpora(SKILLS, run_root)
    results = run_root / "results"

    suite_version = behavioral.get("suite_version")
    thinking = (os.environ.get("PI_EVAL_THINKING") or "").strip() or None
    print(
        f"Gate 5 A/A: suite v{suite_version}, {len(cases)} cases, "
        f"{args.repetitions} repetitions, {observations} observations, "
        f"{model_calls} model calls",
        file=sys.stderr,
        flush=True,
    )
    print(f"Model: {model}; thinking: {thinking or 'provider default'}", file=sys.stderr)
    print(f"Artifacts: {run_root}", file=sys.stderr)

    command = _build_harness_command(
        corpus_a=corpus_a,
        corpus_b=corpus_b,
        results=results,
        repetitions=args.repetitions,
        seed=args.seed,
        timeout=args.timeout,
    )
    returncode = _run_with_progress(command, results=results, total=observations)
    report_path = results / "report.json"
    if not report_path.is_file():
        print(
            json.dumps(
                {
                    "runner_error": {
                        "code": "aa_report_missing",
                        "message": "The A/A harness ended without a report.",
                        "run_root": str(run_root),
                        "exit_code": returncode,
                    }
                },
                separators=(",", ":"),
            )
        )
        return returncode or 2

    report = _load_json(report_path)
    compact = {
        "schema_version": 1,
        "kind": "gate5-aa-noise-floor",
        "gate5_evidence": report.get("gate", {}).get("passed") is True,
        "suite_version": suite_version,
        "model": model,
        "thinking": thinking,
        "case_count": len(cases),
        "repetitions": args.repetitions,
        "observations": observations,
        "expected_model_calls": model_calls,
        "gate": report.get("gate"),
        "summary": report.get("summary"),
        "report_path": str(report_path),
        "runs_path": str(results / "runs.jsonl"),
    }
    print(json.dumps(compact, ensure_ascii=False, separators=(",", ":")))
    return 0 if compact["gate5_evidence"] else 5


if __name__ == "__main__":
    raise SystemExit(main())
