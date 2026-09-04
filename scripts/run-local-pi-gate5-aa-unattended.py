#!/usr/bin/env python3
"""Run or resume one Gate 5 A/A checkpoint unattended for a bounded time.

The coordinator reads the model, provider, thinking level, seed, repetition
count, and corpus snapshot from ``run-metadata.json``. It never starts A/B and
never accesses PROCESIO. Completed observations remain in ``runs.jsonl`` after
every batch.

A one-call model preflight runs at startup and again only after quota/rate-limit
interruptions. Successful batches continue automatically. Quota failures use
bounded exponential backoff until the wall-clock deadline, call budget, A/A
completion, or a non-retryable error stops the coordinator.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
PREFLIGHT = ROOT / "scripts" / "pi-eval-preflight.py"
AA_RUNNER = ROOT / "scripts" / "run-local-pi-gate5-aa.py"
INCOMPLETE_EXIT = 75


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return value


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _parse_last_object(text: str) -> dict[str, Any]:
    for line in reversed([item.strip() for item in text.splitlines() if item.strip()]):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise ValueError("child command did not print a JSON object")


def _checkpoint_count(run_root: Path) -> int:
    path = run_root / "results" / "runs.jsonl"
    if not path.is_file():
        return 0
    count = 0
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_number}: invalid checkpoint JSON") from exc
        if not isinstance(value, dict):
            raise ValueError(f"{path}:{line_number}: checkpoint row must be an object")
        count += 1
    return count


def _locked_state(run_root: Path) -> dict[str, Any]:
    metadata_path = run_root / "run-metadata.json"
    if not metadata_path.is_file():
        raise FileNotFoundError(
            f"missing {metadata_path}; adopt the checkpoint once with the normal A/A runner first"
        )
    metadata = _load_json(metadata_path)
    required = ("model", "case_count", "repetitions", "seed")
    missing = [key for key in required if metadata.get(key) in (None, "")]
    if missing:
        raise ValueError(f"{metadata_path}: missing locked field(s): {', '.join(missing)}")

    total = int(metadata["case_count"]) * int(metadata["repetitions"]) * 2
    completed = _checkpoint_count(run_root)
    if completed > total:
        raise ValueError(f"checkpoint has {completed} rows but metadata expects {total}")
    return {
        "metadata": metadata,
        "total": total,
        "completed": completed,
        "remaining": total - completed,
    }


def _runner_error(value: dict[str, Any]) -> dict[str, Any] | None:
    error = value.get("runner_error")
    return error if isinstance(error, dict) else None


def _is_quota_or_rate_limit(value: dict[str, Any]) -> bool:
    error = _runner_error(value)
    fields: list[str] = []
    if error:
        fields.extend(str(error.get(key) or "") for key in ("code", "failure_class", "message"))
    fields.extend(str(value.get(key) or "") for key in ("code", "failure_class", "diagnosis"))
    text = " ".join(fields).lower()
    return any(token in text for token in ("quota", "rate_limit", "rate limit", "limit exhausted"))


def _is_complete_result(value: dict[str, Any]) -> bool:
    return value.get("kind") == "gate5-aa-noise-floor"


def _invoke_preflight(
    *,
    model: str,
    provider: str | None,
    thinking: str | None,
    timeout: int,
    env: dict[str, str],
) -> tuple[int, dict[str, Any]]:
    command = [sys.executable, str(PREFLIGHT), "--model", model, "--timeout", str(timeout)]
    if provider:
        command += ["--provider", provider]
    if thinking:
        command += ["--thinking", thinking]
    process = subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    if process.stderr.strip():
        print(process.stderr.strip(), file=sys.stderr, flush=True)
    return process.returncode, _parse_last_object(process.stdout)


def _invoke_batch(
    *,
    run_root: Path,
    repetitions: int,
    seed: int,
    observations: int,
    timeout: int,
    env: dict[str, str],
) -> tuple[int, dict[str, Any]]:
    command = [
        sys.executable,
        str(AA_RUNNER),
        "--resume-run",
        str(run_root),
        "--repetitions",
        str(repetitions),
        "--seed",
        str(seed),
        "--timeout",
        str(timeout),
        "--max-new-observations",
        str(observations),
        "--confirm-model-calls",
        str(observations * 2),
    ]
    # Preserve the A/A runner's progress lines in the caller's log while keeping
    # its final compact JSON available for orchestration.
    process = subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=None,
        check=False,
    )
    return process.returncode, _parse_last_object(process.stdout)


def _status_payload(
    *,
    run_root: Path,
    state: dict[str, Any],
    started_at: str,
    status: str,
    stop_reason: str | None,
    call_upper_bound: int,
    max_model_calls: int,
    preflight_attempts: int,
    batch_attempts: int,
    last_result: dict[str, Any] | None,
) -> dict[str, Any]:
    metadata = state["metadata"]
    return {
        "schema_version": 1,
        "kind": "gate5-aa-unattended-status",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "started_at": started_at,
        "status": status,
        "stop_reason": stop_reason,
        "run_root": str(run_root),
        "model": metadata.get("model"),
        "provider": metadata.get("provider"),
        "thinking": metadata.get("thinking"),
        "completed_observations": state["completed"],
        "remaining_observations": state["remaining"],
        "model_calls_upper_bound": call_upper_bound,
        "max_model_calls": max_model_calls,
        "preflight_attempts": preflight_attempts,
        "batch_attempts": batch_attempts,
        "gate5_evidence": bool(last_result and last_result.get("gate5_evidence") is True),
        "last_result": last_result,
    }


def run_unattended(
    *,
    run_root: Path,
    max_hours: float,
    batch_observations: int,
    initial_backoff_seconds: float,
    max_backoff_seconds: float,
    between_batches_seconds: float,
    preflight_timeout: int,
    observation_timeout: int,
    max_model_calls: int,
    preflight_fn: Callable[..., tuple[int, dict[str, Any]]] = _invoke_preflight,
    batch_fn: Callable[..., tuple[int, dict[str, Any]]] = _invoke_batch,
    sleep_fn: Callable[[float], None] = time.sleep,
    monotonic_fn: Callable[[], float] = time.monotonic,
) -> tuple[int, dict[str, Any]]:
    run_root = run_root.expanduser().resolve()
    state = _locked_state(run_root)
    metadata = state["metadata"]
    model = str(metadata["model"])
    provider = str(metadata["provider"]) if metadata.get("provider") else None
    thinking = str(metadata["thinking"]) if metadata.get("thinking") else None
    repetitions = int(metadata["repetitions"])
    seed = int(metadata["seed"])

    env = os.environ.copy()
    env["PI_EVAL_MODEL"] = model
    if provider:
        env["PI_EVAL_PROVIDER"] = provider
    else:
        env.pop("PI_EVAL_PROVIDER", None)
    if thinking:
        env["PI_EVAL_THINKING"] = thinking
    else:
        env.pop("PI_EVAL_THINKING", None)

    started_at = datetime.now(timezone.utc).isoformat()
    deadline = monotonic_fn() + max_hours * 3600
    call_upper_bound = 0
    preflight_attempts = 0
    batch_attempts = 0
    backoff = initial_backoff_seconds
    needs_preflight = True
    last_result: dict[str, Any] | None = None
    status_path = run_root / "unattended-status.json"

    def finish(exit_code: int, status: str, reason: str) -> tuple[int, dict[str, Any]]:
        current = _locked_state(run_root)
        payload = _status_payload(
            run_root=run_root,
            state=current,
            started_at=started_at,
            status=status,
            stop_reason=reason,
            call_upper_bound=call_upper_bound,
            max_model_calls=max_model_calls,
            preflight_attempts=preflight_attempts,
            batch_attempts=batch_attempts,
            last_result=last_result,
        )
        _write_json(status_path, payload)
        print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
        return exit_code, payload

    while True:
        state = _locked_state(run_root)
        if state["remaining"] == 0:
            result_path = run_root / "results" / "report.json"
            if result_path.is_file():
                report = _load_json(result_path)
                passed = report.get("gate", {}).get("passed") is True
                last_result = {
                    "kind": "gate5-aa-noise-floor",
                    "gate5_evidence": passed,
                    "gate": report.get("gate"),
                    "summary": report.get("summary"),
                    "report_path": str(result_path),
                }
                return finish(0 if passed else 5, "complete", "aa_passed" if passed else "aa_noise_gate_failed")
            return finish(2, "error", "complete_checkpoint_missing_report")

        now = monotonic_fn()
        if now >= deadline:
            return finish(INCOMPLETE_EXIT, "paused", "wall_clock_deadline")
        if call_upper_bound >= max_model_calls:
            return finish(INCOMPLETE_EXIT, "paused", "model_call_budget")

        if needs_preflight:
            if call_upper_bound + 1 > max_model_calls:
                return finish(INCOMPLETE_EXIT, "paused", "model_call_budget")
            preflight_attempts += 1
            print(
                f"Preflight {preflight_attempts}: {model} ({thinking or 'provider default'})",
                file=sys.stderr,
                flush=True,
            )
            _code, preflight = preflight_fn(
                model=model,
                provider=provider,
                thinking=thinking,
                timeout=preflight_timeout,
                env=env,
            )
            call_upper_bound += 1
            last_result = preflight
            if preflight.get("ready") is not True:
                if not _is_quota_or_rate_limit(preflight):
                    return finish(2, "error", "preflight_non_retryable")
                remaining_seconds = max(0.0, deadline - monotonic_fn())
                delay = min(backoff, remaining_seconds)
                if delay <= 0:
                    return finish(INCOMPLETE_EXIT, "paused", "wall_clock_deadline")
                print(
                    f"Model unavailable from quota/rate limit; backing off {int(delay)}s",
                    file=sys.stderr,
                    flush=True,
                )
                _write_json(
                    status_path,
                    _status_payload(
                        run_root=run_root,
                        state=state,
                        started_at=started_at,
                        status="backing_off",
                        stop_reason="quota_or_rate_limit",
                        call_upper_bound=call_upper_bound,
                        max_model_calls=max_model_calls,
                        preflight_attempts=preflight_attempts,
                        batch_attempts=batch_attempts,
                        last_result=last_result,
                    ),
                )
                sleep_fn(delay)
                backoff = min(max_backoff_seconds, max(initial_backoff_seconds, backoff * 2))
                continue
            needs_preflight = False
            backoff = initial_backoff_seconds

        state = _locked_state(run_root)
        budget_observations = (max_model_calls - call_upper_bound) // 2
        batch = min(batch_observations, state["remaining"], budget_observations)
        if batch < 1:
            return finish(INCOMPLETE_EXIT, "paused", "model_call_budget")

        before = state["completed"]
        batch_attempts += 1
        print(
            f"Batch {batch_attempts}: up to {batch} observations; checkpoint {before}/{state['total']}",
            file=sys.stderr,
            flush=True,
        )
        returncode, result = batch_fn(
            run_root=run_root,
            repetitions=repetitions,
            seed=seed,
            observations=batch,
            timeout=observation_timeout,
            env=env,
        )
        last_result = result
        after_state = _locked_state(run_root)
        added = max(0, after_state["completed"] - before)
        failed_in_flight = bool(
            (_runner_error(result) or returncode not in (0, 5, INCOMPLETE_EXIT))
            and added < batch
        )
        call_upper_bound += 2 * added + (2 if failed_in_flight else 0)
        call_upper_bound = min(call_upper_bound, max_model_calls)

        _write_json(
            status_path,
            _status_payload(
                run_root=run_root,
                state=after_state,
                started_at=started_at,
                status="running" if after_state["remaining"] else "complete",
                stop_reason=None,
                call_upper_bound=call_upper_bound,
                max_model_calls=max_model_calls,
                preflight_attempts=preflight_attempts,
                batch_attempts=batch_attempts,
                last_result=last_result,
            ),
        )

        if _is_complete_result(result) or after_state["remaining"] == 0:
            passed = result.get("gate5_evidence") is True
            return finish(0 if passed else 5, "complete", "aa_passed" if passed else "aa_noise_gate_failed")

        if _is_quota_or_rate_limit(result):
            needs_preflight = True
            remaining_seconds = max(0.0, deadline - monotonic_fn())
            delay = min(backoff, remaining_seconds)
            if delay <= 0:
                return finish(INCOMPLETE_EXIT, "paused", "wall_clock_deadline")
            print(
                f"Batch hit quota/rate limit after {added} new observations; backing off {int(delay)}s",
                file=sys.stderr,
                flush=True,
            )
            sleep_fn(delay)
            backoff = min(max_backoff_seconds, max(initial_backoff_seconds, backoff * 2))
            continue

        if returncode == INCOMPLETE_EXIT and result.get("status") == "paused":
            backoff = initial_backoff_seconds
            delay = min(between_batches_seconds, max(0.0, deadline - monotonic_fn()))
            if delay > 0:
                sleep_fn(delay)
            continue

        return finish(2, "error", "batch_non_retryable")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resume-run", type=Path, required=True)
    parser.add_argument("--max-hours", type=float, default=5.0)
    parser.add_argument("--batch-observations", type=int, default=8)
    parser.add_argument("--initial-backoff-seconds", type=float, default=300)
    parser.add_argument("--max-backoff-seconds", type=float, default=1800)
    parser.add_argument("--between-batches-seconds", type=float, default=30)
    parser.add_argument("--preflight-timeout", type=int, default=120)
    parser.add_argument("--observation-timeout", type=int, default=900)
    parser.add_argument(
        "--confirm-max-model-calls",
        type=int,
        required=True,
        help="hard upper bound for preflight and evaluation model calls in this unattended session",
    )
    args = parser.parse_args(argv)

    if args.max_hours <= 0:
        parser.error("--max-hours must be positive")
    if args.batch_observations < 1:
        parser.error("--batch-observations must be positive")
    if args.initial_backoff_seconds < 1:
        parser.error("--initial-backoff-seconds must be at least 1")
    if args.max_backoff_seconds < args.initial_backoff_seconds:
        parser.error("--max-backoff-seconds must be >= --initial-backoff-seconds")
    if args.between_batches_seconds < 0:
        parser.error("--between-batches-seconds cannot be negative")
    if args.confirm_max_model_calls < 1:
        parser.error("--confirm-max-model-calls must be positive")

    try:
        initial = _locked_state(args.resume_run.expanduser().resolve())
    except Exception as exc:  # noqa: BLE001 - emit one safe startup error
        print(
            json.dumps(
                {
                    "runner_error": {
                        "code": "unattended_startup_failed",
                        "message": str(exc)[:500],
                    }
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )
        return 2

    minimum_without_interruptions = initial["remaining"] * 2 + (1 if initial["remaining"] else 0)
    print(
        f"Unattended A/A: {initial['completed']}/{initial['total']} complete, "
        f"{initial['remaining']} remaining; deadline {args.max_hours:g}h; "
        f"call cap {args.confirm_max_model_calls} (minimum without interruptions: "
        f"{minimum_without_interruptions})",
        file=sys.stderr,
        flush=True,
    )
    try:
        exit_code, _payload = run_unattended(
            run_root=args.resume_run,
            max_hours=args.max_hours,
            batch_observations=args.batch_observations,
            initial_backoff_seconds=args.initial_backoff_seconds,
            max_backoff_seconds=args.max_backoff_seconds,
            between_batches_seconds=args.between_batches_seconds,
            preflight_timeout=args.preflight_timeout,
            observation_timeout=args.observation_timeout,
            max_model_calls=args.confirm_max_model_calls,
        )
        return exit_code
    except KeyboardInterrupt:
        state = _locked_state(args.resume_run.expanduser().resolve())
        payload = {
            "schema_version": 1,
            "kind": "gate5-aa-unattended-status",
            "status": "paused",
            "stop_reason": "operator_interrupt",
            "completed_observations": state["completed"],
            "remaining_observations": state["remaining"],
            "run_root": str(args.resume_run.expanduser().resolve()),
        }
        _write_json(args.resume_run.expanduser().resolve() / "unattended-status.json", payload)
        print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
        return INCOMPLETE_EXIT
    except Exception as exc:  # noqa: BLE001 - emit one safe unattended error
        print(
            json.dumps(
                {
                    "runner_error": {
                        "code": "unattended_runner_failed",
                        "message": str(exc)[:500],
                        "run_root": str(args.resume_run.expanduser().resolve()),
                    }
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
