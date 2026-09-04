"""Checkpointed fixed-jury Gate 5 execution pipeline."""
from __future__ import annotations

import os
import shlex
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .common import (
    INCOMPLETE,
    PHASES,
    command,
    load,
    parse_output,
    prepare,
    retryable,
    rows,
    write_status,
)


def invoke_preflight(
    run_root: Path,
    metadata: dict[str, Any],
    env: dict[str, str],
    timeout: int,
) -> tuple[int, dict[str, Any]]:
    argv = [
        sys.executable,
        str(run_root / "evaluator" / "pi-eval-preflight.py"),
        "--model",
        str(metadata["model"]),
        "--thinking",
        str(metadata["thinking"]),
        "--timeout",
        str(timeout),
    ]
    if metadata.get("provider"):
        argv += ["--provider", str(metadata["provider"])]
    result = command(
        argv,
        cwd=Path(metadata["repo"]),
        env=env,
        timeout=timeout + 30,
    )
    if result.stderr.strip():
        print(result.stderr.strip()[-2000:], file=sys.stderr)
    return result.returncode, parse_output(result.stdout)


def invoke_batch(
    run_root: Path,
    metadata: dict[str, Any],
    phase: str,
    mode: str,
    seed: int,
    batch: int,
    env: dict[str, str],
    timeout: int,
    outer_timeout: int,
) -> tuple[int, dict[str, Any]]:
    candidate = run_root / "snapshots" / "candidate" / "skills"
    other_name = "control" if phase == "aa" else "baseline"
    other = run_root / "snapshots" / other_name / "skills"
    workspace = run_root / "phases" / phase
    workspace.mkdir(parents=True, exist_ok=True)
    argv = [
        sys.executable,
        str(run_root / "evaluator" / "run-skill-behavior-evals.py"),
        "--mode",
        mode,
        "--candidate-root",
        str(candidate),
        "--baseline-root",
        str(other),
        "--evals",
        str(candidate / "evals" / "behavioral.json"),
        "--thresholds",
        str(candidate / "evals" / "gate5-thresholds.json"),
        "--runner",
        shlex.join(
            [
                sys.executable,
                str(run_root / "evaluator" / "pi-skill-eval-runner-strict.py"),
            ]
        ),
        "--workspace",
        str(workspace),
        "--repetitions",
        str(metadata["repetitions"]),
        "--seed",
        str(seed),
        "--timeout",
        str(timeout),
        "--max-new-observations",
        str(batch),
    ]
    if (workspace / "runs.jsonl").exists():
        argv.append("--resume")
    result = command(
        argv,
        cwd=Path(metadata["repo"]),
        env=env,
        timeout=outer_timeout,
    )
    if result.stderr.strip():
        print(result.stderr.strip()[-4000:], file=sys.stderr)
    for name in ("report.json", "partial-report.json"):
        path = workspace / name
        if path.is_file():
            return result.returncode, load(path)
    return result.returncode, parse_output(result.stdout)


def run_pipeline(args: Any) -> int:
    repo = args.repo.expanduser().resolve()
    if args.resume_run:
        run_root = args.resume_run.expanduser().resolve()
        metadata = load(run_root / "run-metadata.json")
        for key, expected in (
            ("repo", str(repo)),
            ("model", args.model),
            ("provider", args.provider),
            ("thinking", args.thinking),
        ):
            if metadata.get(key) != expected:
                raise RuntimeError(f"cannot resume: {key} changed")
    else:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        run_root = (
            args.out_root
            or repo / "scratchpad" / f"gate5-fixed-jury-v3-{stamp}"
        ).expanduser().resolve()
        run_root.mkdir(parents=True, exist_ok=True)
        allowed = {"overnight.log", "overnight.pid"}
        unexpected = sorted(
            path.name for path in run_root.iterdir() if path.name not in allowed
        )
        if unexpected:
            raise FileExistsError(
                f"new run directory is not empty: {run_root} "
                f"({', '.join(unexpected)})"
            )
        metadata = prepare(repo, run_root, args)

    latest = repo / "scratchpad" / "gate5-latest-run.txt"
    latest.parent.mkdir(parents=True, exist_ok=True)
    latest.write_text(str(run_root) + "\n", encoding="utf-8")

    started = datetime.now(timezone.utc).isoformat()
    deadline = time.monotonic() + args.max_hours * 3600
    calls = 0
    backoff = args.initial_backoff_seconds
    need_preflight = True
    last: dict[str, Any] | None = None
    env = os.environ.copy()
    env.update(
        {
            "PI_EVAL_MODEL": args.model,
            "PI_EVAL_THINKING": args.thinking,
            "PI_EVAL_CALL_TIMEOUT": str(args.model_call_timeout),
        }
    )
    if args.provider:
        env["PI_EVAL_PROVIDER"] = args.provider
    else:
        env.pop("PI_EVAL_PROVIDER", None)

    def finish(code: int, status: str, reason: str, phase: str | None) -> int:
        write_status(
            run_root,
            metadata,
            status=status,
            reason=reason,
            phase=phase,
            calls=calls,
            cap=args.confirm_max_model_calls,
            started=started,
            last=last,
        )
        return code

    total = int(metadata["observations_per_phase"])
    for phase, mode, seed in PHASES:
        report_path = run_root / "phases" / phase / "report.json"
        if report_path.is_file():
            report = load(report_path)
            if not (report.get("gate") or {}).get("passed"):
                last = report
                reason = (
                    "aa_noise_gate_failed"
                    if phase == "aa"
                    else f"{phase}_gate_failed"
                )
                return finish(5, "blocked", reason, phase)
            continue

        while not report_path.is_file():
            if time.monotonic() >= deadline:
                return finish(INCOMPLETE, "paused", "wall_clock_deadline", phase)
            if calls >= args.confirm_max_model_calls:
                return finish(INCOMPLETE, "paused", "model_call_budget", phase)

            if need_preflight:
                print(
                    f"Preflight: {args.model} ({args.thinking})",
                    file=sys.stderr,
                    flush=True,
                )
                _code, last = invoke_preflight(
                    run_root, metadata, env, args.preflight_timeout
                )
                calls += 1
                if last.get("ready") is not True:
                    if not retryable(last):
                        return finish(2, "error", "preflight_non_retryable", phase)
                    delay = min(
                        backoff, max(0.0, deadline - time.monotonic())
                    )
                    if delay <= 0:
                        return finish(
                            INCOMPLETE, "paused", "wall_clock_deadline", phase
                        )
                    print(
                        f"Quota/rate limit; sleeping {int(delay)}s",
                        file=sys.stderr,
                        flush=True,
                    )
                    time.sleep(delay)
                    backoff = min(args.max_backoff_seconds, backoff * 2)
                    continue
                need_preflight = False
                backoff = args.initial_backoff_seconds

            before = rows(run_root / "phases" / phase / "runs.jsonl")
            remaining = total - before
            budget = (args.confirm_max_model_calls - calls) // 2
            batch = min(args.batch_observations, remaining, budget)
            if batch < 1:
                return finish(INCOMPLETE, "paused", "model_call_budget", phase)
            print(
                f"{phase}: {before}/{total}; next batch {batch}",
                file=sys.stderr,
                flush=True,
            )
            outer_timeout = min(
                batch * (args.observation_timeout + 60),
                max(60, int(deadline - time.monotonic())),
            )
            try:
                returncode, last = invoke_batch(
                    run_root,
                    metadata,
                    phase,
                    mode,
                    seed,
                    batch,
                    env,
                    args.observation_timeout,
                    outer_timeout,
                )
            except subprocess.TimeoutExpired:
                after = rows(run_root / "phases" / phase / "runs.jsonl")
                added = max(0, after - before)
                calls = min(
                    args.confirm_max_model_calls, calls + 2 * added + 2
                )
                last = {
                    "runner_error": {
                        "code": "phase_batch_timeout",
                        "message": (
                            "The bounded phase batch timed out; checkpoint rows "
                            "remain resumable."
                        ),
                    }
                }
                return finish(
                    INCOMPLETE, "paused", "phase_batch_timeout", phase
                )

            after = rows(run_root / "phases" / phase / "runs.jsonl")
            added = max(0, after - before)
            calls += 2 * added
            if (
                returncode not in (0, 5, INCOMPLETE) or retryable(last)
            ) and added < batch:
                calls = min(args.confirm_max_model_calls, calls + 2)

            if report_path.is_file():
                report = load(report_path)
                last = report
                if not (report.get("gate") or {}).get("passed"):
                    reason = (
                        "aa_noise_gate_failed"
                        if phase == "aa"
                        else f"{phase}_gate_failed"
                    )
                    return finish(5, "blocked", reason, phase)
                print(f"{phase}: passed", file=sys.stderr, flush=True)
                break

            if retryable(last):
                need_preflight = True
                delay = min(backoff, max(0.0, deadline - time.monotonic()))
                if delay <= 0:
                    return finish(
                        INCOMPLETE, "paused", "wall_clock_deadline", phase
                    )
                print(
                    f"{phase}: quota/rate limit; sleeping {int(delay)}s",
                    file=sys.stderr,
                    flush=True,
                )
                time.sleep(delay)
                backoff = min(args.max_backoff_seconds, backoff * 2)
                continue
            if returncode == INCOMPLETE and last.get("status") == "paused":
                delay = min(
                    args.between_batches_seconds,
                    max(0.0, deadline - time.monotonic()),
                )
                if delay:
                    time.sleep(delay)
                continue
            return finish(2, "error", "phase_non_retryable", phase)

    verify = command(
        [
            sys.executable,
            str(run_root / "evaluator" / "verify-skill-eval-series.py"),
            str(run_root / "phases" / "ab-round-1" / "report.json"),
            str(run_root / "phases" / "ab-round-2" / "report.json"),
            "--thresholds",
            str(
                run_root
                / "snapshots"
                / "candidate"
                / "skills"
                / "evals"
                / "gate5-thresholds.json"
            ),
            "--out",
            str(run_root / "series.json"),
        ],
        cwd=repo,
    )
    last = (
        load(run_root / "series.json")
        if (run_root / "series.json").is_file()
        else parse_output(verify.stdout)
    )
    if verify.returncode or last.get("passed") is not True:
        return finish(5, "blocked", "series_verification_failed", None)
    return finish(0, "complete", "all_gate5_rounds_passed", None)
