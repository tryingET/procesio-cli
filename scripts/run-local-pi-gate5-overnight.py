#!/usr/bin/env -S uv run --script
#
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""PEP 723 uv entry point for the canonical checkpointed Gate 5 series runner.

Use either:

    uv run --script scripts/run-local-pi-gate5-overnight.py --help

or execute this file directly after making it executable. All evaluation,
checkpointing, fixed-jury validation, phase gating, quota backoff, and status
reporting remain in ``run-local-pi-gate5-series-unattended.py`` so there is one
source of truth.

This entry point adds only process-level recovery. A Pi process can occasionally
exit before returning an evaluation result even after a successful preflight.
That leaves the current observation absent from the JSONL checkpoint. Such an
uncommitted, read-only observation is safe to retry. The launcher therefore
restarts the canonical coordinator a bounded number of times for the exact
``pi_invocation_failed`` condition; every restart re-runs the normal preflight
and resumes the frozen corpus, rubric, evaluator, model, and remaining schedule.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
TARGET = Path(__file__).with_name("run-local-pi-gate5-series-unattended.py")
DEFAULT_RUN_ROOT = ROOT / "scratchpad" / "gate5-series-v3-overnight"


def _run_root(argv: list[str]) -> Path:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--run-root", type=Path, default=DEFAULT_RUN_ROOT)
    args, _unknown = parser.parse_known_args(argv)
    return args.run_root.expanduser().resolve()


def _load_status(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _runner_error_code(status: dict[str, Any]) -> str | None:
    last = status.get("last_result")
    if not isinstance(last, dict):
        return None
    candidates: list[Any] = [last.get("runner_error")]
    interruption = last.get("interruption")
    if isinstance(interruption, dict):
        candidates.append(interruption.get("runner_error"))
    for candidate in candidates:
        if isinstance(candidate, dict) and isinstance(candidate.get("code"), str):
            return candidate["code"]
    return None


def _transient_pi_exit(returncode: int, status: dict[str, Any] | None) -> bool:
    return bool(
        returncode == 2
        and isinstance(status, dict)
        and status.get("status") == "error"
        and status.get("stop_reason") == "phase_non_retryable"
        and int(status.get("remaining_observations") or 0) > 0
        and _runner_error_code(status) == "pi_invocation_failed"
    )


def _positive_int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise SystemExit(f"{name} must be an integer, not {raw!r}") from exc
    if value < 0:
        raise SystemExit(f"{name} cannot be negative")
    return value


def main(argv: list[str] | None = None) -> int:
    if not TARGET.is_file():
        raise SystemExit(f"canonical Gate 5 runner is missing: {TARGET}")

    forwarded = list(sys.argv[1:] if argv is None else argv)
    status_path = _run_root(forwarded) / "series-status.json"
    max_restarts = _positive_int_env("GATE5_TRANSIENT_RESTARTS", 3)
    initial_delay = _positive_int_env("GATE5_TRANSIENT_RETRY_SECONDS", 30)

    for restart in range(max_restarts + 1):
        try:
            process = subprocess.run(
                [sys.executable, str(TARGET), *forwarded],
                cwd=ROOT,
                env=os.environ.copy(),
                check=False,
            )
        except KeyboardInterrupt:
            return 130

        status = _load_status(status_path)
        if not _transient_pi_exit(int(process.returncode), status):
            return int(process.returncode)
        if restart >= max_restarts:
            print(
                "Gate 5 stopped after the bounded transient Pi restart budget; "
                f"the checkpoint remains resumable at {status_path}.",
                file=sys.stderr,
                flush=True,
            )
            return int(process.returncode)

        delay = min(initial_delay * (2**restart), 120)
        completed = int(status.get("completed_observations") or 0) if status else 0
        remaining = int(status.get("remaining_observations") or 0) if status else 0
        print(
            "Pi exited before committing an evaluation result; "
            f"checkpoint is {completed} complete / {remaining} remaining. "
            f"Re-preflighting and resuming in {delay}s "
            f"({restart + 1}/{max_restarts} bounded restarts).",
            file=sys.stderr,
            flush=True,
        )
        time.sleep(delay)

    return 2  # pragma: no cover - loop always returns


if __name__ == "__main__":
    raise SystemExit(main())
