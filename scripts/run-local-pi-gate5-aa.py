#!/usr/bin/env python3
"""Run or resume the formal local Pi Gate 5 A/A noise-floor experiment.

The helper copies one skill corpus into two independent directories, invokes the
paired behavioral harness in A/A mode, shows observation progress, and emits one
compact summary. It never accesses PROCESIO.

Each completed observation is checkpointed. Use ``--resume-run`` after a quota
or rate-limit stop. ``--max-new-observations`` allows deliberately small batches;
the explicit model-call confirmation applies only to the next batch.
"""
from __future__ import annotations

import argparse
import hashlib
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
HARNESS = ROOT / "scripts" / "run-skill-behavior-evals.py"
STRICT_RUNNER = ROOT / "scripts" / "pi-skill-eval-runner-strict.py"
INCOMPLETE_EXIT = 75


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return value


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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


def _expected_counts(*, case_count: int, repetitions: int) -> tuple[int, int]:
    observations = case_count * repetitions * 2
    return observations, observations * 2


def _batch_counts(
    *,
    total_observations: int,
    completed_observations: int,
    max_new_observations: int | None,
) -> tuple[int, int, int]:
    remaining = max(0, total_observations - completed_observations)
    batch = remaining if max_new_observations is None else min(remaining, max_new_observations)
    return remaining, batch, batch * 2


def _join_argv(argv: list[str], *, platform: str | None = None) -> str:
    platform = os.name if platform is None else platform
    if platform == "nt":
        return subprocess.list2cmdline(argv)
    return shlex.join(argv)


def _copy_independent_corpora(source: Path, run_root: Path) -> tuple[Path, Path]:
    if run_root.exists():
        raise FileExistsError(
            f"run directory already exists: {run_root}. Choose a new --out-root "
            "or use --resume-run."
        )
    run_root.mkdir(parents=True)
    corpus_a = run_root / "corpus-a"
    corpus_b = run_root / "corpus-b"
    shutil.copytree(source, corpus_a)
    shutil.copytree(source, corpus_b)
    return corpus_a, corpus_b


def _snapshot_paths(run_root: Path) -> tuple[Path, Path, Path, Path, Path]:
    corpus_a = run_root / "corpus-a"
    corpus_b = run_root / "corpus-b"
    results = run_root / "results"
    evals = corpus_a / "evals" / "behavioral.json"
    thresholds = corpus_a / "evals" / "gate5-thresholds.json"
    for path in (corpus_a, corpus_b):
        if not path.is_dir():
            raise FileNotFoundError(f"A/A corpus directory is missing: {path}")
    for path in (evals, thresholds):
        if not path.is_file():
            raise FileNotFoundError(f"A/A snapshot file is missing: {path}")
    if _fingerprint(corpus_a) != _fingerprint(corpus_b):
        raise ValueError("A/A corpus copies are no longer byte-identical")
    return corpus_a, corpus_b, results, evals, thresholds


def _checkpoint_rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_number}: invalid checkpoint JSON") from exc
        if not isinstance(row, dict):
            raise ValueError(f"{path}:{line_number}: checkpoint row must be an object")
        rows.append(row)
    return rows


def _completed_rows(path: Path) -> tuple[int, str | None]:
    rows = _checkpoint_rows(path)
    if not rows:
        return 0, None
    row = rows[-1]
    label = None
    case_id = row.get("case_id")
    repetition = row.get("repetition")
    if case_id is not None and repetition is not None:
        label = f"{case_id}, repetition {int(repetition) + 1}"
    return len(rows), label


def _metadata_expected(
    *,
    model: str,
    provider: str | None,
    thinking: str | None,
    suite_version: Any,
    case_count: int,
    repetitions: int,
    seed: int,
    corpus_a: Path,
    evals: Path,
    thresholds: Path,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "kind": "gate5-aa-run-metadata",
        "model": model,
        "provider": provider,
        "thinking": thinking,
        "suite_version": suite_version,
        "case_count": case_count,
        "repetitions": repetitions,
        "seed": seed,
        "corpus_fingerprint": _fingerprint(corpus_a),
        "evals_sha256": _sha256_file(evals),
        "thresholds_sha256": _sha256_file(thresholds),
        "strict_runner_sha256": _sha256_file(STRICT_RUNNER),
    }


def _validate_or_adopt_metadata(
    path: Path,
    expected: dict[str, Any],
    *,
    completed: int,
    confirm_existing: int | None,
) -> dict[str, Any]:
    if path.is_file():
        actual = _load_json(path)
        for key, value in expected.items():
            if actual.get(key) != value:
                raise ValueError(
                    f"cannot resume: {key} changed from {actual.get(key)!r} to {value!r}"
                )
        if confirm_existing is not None and confirm_existing != completed:
            raise ValueError(
                f"--confirm-existing-observations is {confirm_existing}, but checkpoint has {completed}"
            )
        return actual

    if completed and confirm_existing != completed:
        raise ValueError(
            "this interrupted run predates automatic metadata. Resume it only with "
            f"--confirm-existing-observations {completed} after checking the original console output"
        )
    if not completed and confirm_existing not in (None, 0):
        raise ValueError("there are no existing observations to confirm")

    rows = _checkpoint_rows(path.parent / "results" / "runs.jsonl")
    observed_models = {
        str(row["evaluation_model"])
        for row in rows
        if row.get("evaluation_model") is not None
    }
    if observed_models and observed_models != {str(expected["model"])}:
        raise ValueError(
            f"checkpoint model(s) {sorted(observed_models)} do not match {expected['model']!r}"
        )

    metadata = {
        **expected,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "adopted_legacy_checkpoint": bool(completed),
        "operator_confirmed_existing_observations": completed if completed else None,
    }
    _write_json(path, metadata)
    return metadata


def _build_harness_command(
    *,
    corpus_a: Path,
    corpus_b: Path,
    results: Path,
    evals: Path,
    thresholds: Path,
    repetitions: int,
    seed: int,
    timeout: int,
    resume: bool,
    max_new_observations: int | None,
    platform: str | None = None,
) -> list[str]:
    runner_command = _join_argv([sys.executable, str(STRICT_RUNNER)], platform=platform)
    command = [
        sys.executable,
        str(HARNESS),
        "--mode",
        "aa",
        "--candidate-root",
        str(corpus_a),
        "--baseline-root",
        str(corpus_b),
        "--evals",
        str(evals),
        "--thresholds",
        str(thresholds),
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
    if resume:
        command.append("--resume")
    if max_new_observations is not None:
        command += ["--max-new-observations", str(max_new_observations)]
    return command


def _run_with_progress(
    command: list[str],
    *,
    results: Path,
    total: int,
) -> tuple[int, str, str]:
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
            print(
                f"[{completed}/{total}] observations complete{suffix}",
                file=sys.stderr,
                flush=True,
            )
            shown = completed
        time.sleep(1)

    stdout, stderr = process.communicate()
    completed, label = _completed_rows(runs_path)
    if completed != shown:
        suffix = f" — {label}" if label else ""
        print(
            f"[{completed}/{total}] observations complete{suffix}",
            file=sys.stderr,
            flush=True,
        )
    if stderr.strip():
        print(stderr.strip(), file=sys.stderr)
    return int(process.returncode or 0), stdout.strip(), stderr.strip()


def _compact_partial(
    *,
    partial: dict[str, Any],
    run_root: Path,
    model: str,
    thinking: str | None,
    suite_version: Any,
) -> dict[str, Any]:
    interruption = partial.get("interruption")
    runner_error = None
    if isinstance(interruption, dict):
        runner_error = interruption.get("runner_error")
    completed = int(partial.get("completed_observations") or 0)
    remaining = int(partial.get("remaining_observations") or 0)
    return {
        "schema_version": 1,
        "kind": "gate5-aa-checkpoint",
        "gate5_evidence": False,
        "status": partial.get("status"),
        "resumable": partial.get("resumable") is True,
        "suite_version": suite_version,
        "model": model,
        "thinking": thinking,
        "completed_observations": completed,
        "remaining_observations": remaining,
        "completed_model_calls_minimum": completed * 2,
        "runner_error": runner_error,
        "run_root": str(run_root),
        "report_path": str(run_root / "results" / "partial-report.json"),
        "runs_path": str(run_root / "results" / "runs.jsonl"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    location = parser.add_mutually_exclusive_group()
    location.add_argument(
        "--out-root",
        type=Path,
        help="new run directory; defaults to a timestamped directory under scratchpad",
    )
    location.add_argument(
        "--resume-run",
        type=Path,
        help="existing Gate 5 A/A run directory to resume",
    )
    parser.add_argument("--repetitions", type=int, default=5)
    parser.add_argument("--seed", type=int, default=20260902)
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument(
        "--max-new-observations",
        type=int,
        help="complete at most this many new observations in this invocation",
    )
    parser.add_argument(
        "--confirm-existing-observations",
        type=int,
        help="required once when adopting a checkpoint created before resume metadata existed",
    )
    parser.add_argument(
        "--confirm-model-calls",
        type=int,
        required=True,
        help="must equal the calculated model-call budget for this invocation",
    )
    args = parser.parse_args(argv)

    model = (os.environ.get("PI_EVAL_MODEL") or "").strip()
    provider = (os.environ.get("PI_EVAL_PROVIDER") or "").strip() or None
    thinking = (os.environ.get("PI_EVAL_THINKING") or "").strip() or None
    if not model:
        parser.error("PI_EVAL_MODEL must contain the exact provider/model ID")
    if args.repetitions < 1:
        parser.error("--repetitions must be positive")
    if args.timeout < 1:
        parser.error("--timeout must be positive")
    if args.max_new_observations is not None and args.max_new_observations < 1:
        parser.error("--max-new-observations must be positive")

    resuming = args.resume_run is not None
    if resuming:
        run_root = args.resume_run.expanduser().resolve()
        if not run_root.is_dir():
            parser.error(f"resume directory does not exist: {run_root}")
        corpus_a, corpus_b, results, evals, thresholds = _snapshot_paths(run_root)
    else:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        run_root = (
            args.out_root.expanduser().resolve()
            if args.out_root
            else ROOT / "scratchpad" / f"gate5-aa-v2-{timestamp}"
        )
        corpus_a, corpus_b = _copy_independent_corpora(SKILLS, run_root)
        corpus_a, corpus_b, results, evals, thresholds = _snapshot_paths(run_root)

    behavioral = _load_json(evals)
    threshold_values = _load_json(thresholds)
    cases = behavioral.get("cases")
    if not isinstance(cases, list) or not cases:
        parser.error(f"{evals}: expected a non-empty cases list")
    minimum_repetitions = int(threshold_values.get("minimum_repetitions", 5))
    if args.repetitions < minimum_repetitions:
        parser.error(
            f"formal A/A requires at least {minimum_repetitions} repetitions"
        )

    total_observations, _total_model_calls = _expected_counts(
        case_count=len(cases), repetitions=args.repetitions
    )
    completed, _last = _completed_rows(results / "runs.jsonl")
    if completed > total_observations:
        parser.error(
            f"checkpoint has {completed} rows but this experiment expects {total_observations}"
        )
    remaining, batch_observations, batch_model_calls = _batch_counts(
        total_observations=total_observations,
        completed_observations=completed,
        max_new_observations=args.max_new_observations,
    )
    if args.confirm_model_calls != batch_model_calls:
        parser.error(
            f"--confirm-model-calls must be {batch_model_calls} for this invocation, "
            f"not {args.confirm_model_calls}"
        )

    suite_version = behavioral.get("suite_version")
    metadata_expected = _metadata_expected(
        model=model,
        provider=provider,
        thinking=thinking,
        suite_version=suite_version,
        case_count=len(cases),
        repetitions=args.repetitions,
        seed=args.seed,
        corpus_a=corpus_a,
        evals=evals,
        thresholds=thresholds,
    )
    _validate_or_adopt_metadata(
        run_root / "run-metadata.json",
        metadata_expected,
        completed=completed,
        confirm_existing=args.confirm_existing_observations,
    )

    if remaining == 0:
        report_path = results / "report.json"
        if not report_path.is_file():
            parser.error("checkpoint is complete but report.json is missing")
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
            "observations": total_observations,
            "expected_model_calls": 0,
            "gate": report.get("gate"),
            "summary": report.get("summary"),
            "report_path": str(report_path),
            "runs_path": str(results / "runs.jsonl"),
        }
        print(json.dumps(compact, ensure_ascii=False, separators=(",", ":")))
        return 0 if compact["gate5_evidence"] else 5

    action = "resume" if resuming or completed else "start"
    print(
        f"Gate 5 A/A {action}: suite v{suite_version}, {len(cases)} cases, "
        f"{args.repetitions} repetitions, {total_observations} total observations",
        file=sys.stderr,
        flush=True,
    )
    print(
        f"Checkpoint: {completed} complete, {remaining} remaining; this batch: "
        f"up to {batch_observations} observations / {batch_model_calls} model calls",
        file=sys.stderr,
    )
    print(f"Model: {model}; thinking: {thinking or 'provider default'}", file=sys.stderr)
    print(f"Artifacts: {run_root}", file=sys.stderr)

    command = _build_harness_command(
        corpus_a=corpus_a,
        corpus_b=corpus_b,
        results=results,
        evals=evals,
        thresholds=thresholds,
        repetitions=args.repetitions,
        seed=args.seed,
        timeout=args.timeout,
        resume=bool(completed or resuming),
        max_new_observations=batch_observations,
    )
    returncode, stdout, _stderr = _run_with_progress(
        command, results=results, total=total_observations
    )

    report_path = results / "report.json"
    if report_path.is_file():
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
            "observations": total_observations,
            "model_calls_authorized_this_invocation": batch_model_calls,
            "gate": report.get("gate"),
            "summary": report.get("summary"),
            "report_path": str(report_path),
            "runs_path": str(results / "runs.jsonl"),
        }
        print(json.dumps(compact, ensure_ascii=False, separators=(",", ":")))
        return 0 if compact["gate5_evidence"] else 5

    partial_path = results / "partial-report.json"
    if partial_path.is_file():
        partial = _load_json(partial_path)
        compact = _compact_partial(
            partial=partial,
            run_root=run_root,
            model=model,
            thinking=thinking,
            suite_version=suite_version,
        )
        print(json.dumps(compact, ensure_ascii=False, separators=(",", ":")))
        return INCOMPLETE_EXIT

    diagnostic: dict[str, Any] | str = stdout
    try:
        parsed = json.loads(stdout) if stdout else None
        if isinstance(parsed, dict):
            diagnostic = parsed
    except json.JSONDecodeError:
        pass
    print(
        json.dumps(
            {
                "runner_error": {
                    "code": "aa_report_missing",
                    "message": "The A/A harness ended without a complete or partial report.",
                    "run_root": str(run_root),
                    "exit_code": returncode,
                    "diagnostic": diagnostic,
                }
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )
    return returncode or 2


if __name__ == "__main__":
    raise SystemExit(main())
