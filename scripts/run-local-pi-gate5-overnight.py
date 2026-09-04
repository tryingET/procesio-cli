#!/usr/bin/env -S uv run --script
#
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Run the fixed-jury Gate 5 A/A → A/B → A/B sequence for up to eight hours.

The entry point is a PEP 723 uv script. It uses only the standard library,
freezes the candidate, control, baseline, rubric, thresholds, and evaluator,
checkpoints every observation, and backs off on provider limits. It never calls
PROCESIO or accesses a PROCESIO workspace.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from _gate5_overnight.common import BASELINE_REF, MODEL, SUITE_VERSION, THINKING
from _gate5_overnight.pipeline import run_pipeline

ROOT = Path(__file__).resolve().parents[1]


def child_command(args: argparse.Namespace, run_root: Path) -> list[str]:
    uv = shutil.which("uv") or "uv"
    argv = [
        uv,
        "run",
        "--script",
        str(Path(__file__).resolve()),
        "--repo",
        str(args.repo.expanduser().resolve()),
        "--out-root",
        str(run_root),
        "--baseline-ref",
        args.baseline_ref,
        "--model",
        args.model,
        "--thinking",
        args.thinking,
        "--repetitions",
        str(args.repetitions),
        "--max-hours",
        str(args.max_hours),
        "--batch-observations",
        str(args.batch_observations),
        "--initial-backoff-seconds",
        str(args.initial_backoff_seconds),
        "--max-backoff-seconds",
        str(args.max_backoff_seconds),
        "--between-batches-seconds",
        str(args.between_batches_seconds),
        "--preflight-timeout",
        str(args.preflight_timeout),
        "--observation-timeout",
        str(args.observation_timeout),
        "--model-call-timeout",
        str(args.model_call_timeout),
        "--confirm-max-model-calls",
        str(args.confirm_max_model_calls),
    ]
    if args.provider:
        argv += ["--provider", args.provider]
    if args.resume_run:
        index = argv.index("--out-root")
        del argv[index : index + 2]
        argv += ["--resume-run", str(args.resume_run.expanduser().resolve())]
    return argv


def launch(args: argparse.Namespace) -> int:
    repo = args.repo.expanduser().resolve()
    if args.resume_run:
        run_root = args.resume_run.expanduser().resolve()
    else:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        run_root = (
            args.out_root
            or repo / "scratchpad" / f"gate5-fixed-jury-v{SUITE_VERSION}-{stamp}"
        ).expanduser().resolve()
    run_root.mkdir(parents=True, exist_ok=True)

    pid_file = run_root / "overnight.pid"
    if pid_file.is_file():
        try:
            old_pid = int(pid_file.read_text(encoding="utf-8").strip())
            os.kill(old_pid, 0)
        except (ValueError, ProcessLookupError, PermissionError):
            pid_file.unlink(missing_ok=True)
        else:
            print(f"Already running as PID {old_pid}\nRun: {run_root}")
            return 0

    log_path = run_root / "overnight.log"
    log = log_path.open("a", encoding="utf-8")
    argv = child_command(args, run_root)
    inhibitor = shutil.which("systemd-inhibit")
    if inhibitor:
        probe = subprocess.run(
            [inhibitor, "--list"],
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if probe.returncode == 0:
            argv = [
                inhibitor,
                "--what=sleep:idle",
                "--mode=block",
                "--why=PROCESIO CLI Gate 5 evaluation",
                *argv,
            ]

    process = subprocess.Popen(
        argv,
        cwd=repo,
        env=os.environ.copy(),
        stdin=subprocess.DEVNULL,
        stdout=log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
        text=True,
    )
    log.close()
    pid_file.write_text(str(process.pid) + "\n", encoding="utf-8")
    latest = repo / "scratchpad" / "gate5-latest-run.txt"
    latest.parent.mkdir(parents=True, exist_ok=True)
    latest.write_text(str(run_root) + "\n", encoding="utf-8")

    time.sleep(5)
    if process.poll() is not None:
        pid_file.unlink(missing_ok=True)
        print("The overnight runner exited during startup.", file=sys.stderr)
        print(log_path.read_text(encoding="utf-8")[-5000:], file=sys.stderr)
        return int(process.returncode or 2)

    print(f"Started Gate 5 overnight run as PID {process.pid}")
    print(f"Run:    {run_root}")
    print(f"Log:    {log_path}")
    print(f"Status: {run_root / 'overnight-status.json'}")
    print(f"Latest: {latest}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=ROOT)
    location = parser.add_mutually_exclusive_group()
    location.add_argument("--out-root", type=Path)
    location.add_argument("--resume-run", type=Path)
    parser.add_argument("--baseline-ref", default=BASELINE_REF)
    parser.add_argument("--model", default=os.environ.get("PI_EVAL_MODEL", MODEL))
    parser.add_argument("--provider", default=os.environ.get("PI_EVAL_PROVIDER"))
    parser.add_argument(
        "--thinking", default=os.environ.get("PI_EVAL_THINKING", THINKING)
    )
    parser.add_argument("--repetitions", type=int, default=5)
    parser.add_argument("--max-hours", type=float, default=8)
    parser.add_argument("--batch-observations", type=int, default=8)
    parser.add_argument("--initial-backoff-seconds", type=float, default=300)
    parser.add_argument("--max-backoff-seconds", type=float, default=1800)
    parser.add_argument("--between-batches-seconds", type=float, default=30)
    parser.add_argument("--preflight-timeout", type=int, default=120)
    parser.add_argument("--observation-timeout", type=int, default=900)
    parser.add_argument("--model-call-timeout", type=int, default=600)
    parser.add_argument("--confirm-max-model-calls", type=int, required=True)
    parser.add_argument("--detach", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.max_hours <= 0:
        parser.error("--max-hours must be positive")
    if args.repetitions < 1 or args.batch_observations < 1:
        parser.error("--repetitions and --batch-observations must be positive")
    if args.initial_backoff_seconds < 1:
        parser.error("--initial-backoff-seconds must be at least 1")
    if args.max_backoff_seconds < args.initial_backoff_seconds:
        parser.error("--max-backoff-seconds must be >= initial backoff")
    if args.confirm_max_model_calls < 1:
        parser.error("--confirm-max-model-calls must be positive")
    if args.detach:
        return launch(args)
    try:
        return run_pipeline(args)
    except KeyboardInterrupt:
        print(
            "Interrupted; completed observations remain checkpointed.",
            file=sys.stderr,
        )
        return 130
    except Exception as exc:  # noqa: BLE001
        print(
            json.dumps(
                {"status": "error", "message": str(exc)[:2000]},
                separators=(",", ":"),
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
