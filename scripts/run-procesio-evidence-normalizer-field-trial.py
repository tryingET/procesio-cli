#!/usr/bin/env -S uv run --script
#
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Launch the approved Evidence Status Normalizer field trial in local Pi.

The Pi process uses the operator's existing local login and shell/tool access.
The committed field-trial contract strictly limits PROCESIO mutations to one
manual process create and one representative execution. Run in the foreground
so the operator can observe the work and interrupt with Ctrl+C.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TASK = ROOT / "examples" / "procesio" / "evidence-status-normalizer.field-trial.md"
SKILL = ROOT / "skills" / "procesio-cli"
DEFAULT_MODEL = "opencode-go/muse-spark-1.3-contributor"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model",
        default=os.environ.get("PI_FIELD_MODEL", DEFAULT_MODEL),
        help="exact Pi provider/model identifier",
    )
    parser.add_argument(
        "--thinking",
        default=os.environ.get("PI_FIELD_THINKING", "medium"),
    )
    parser.add_argument(
        "--interactive-approval",
        action="store_true",
        help="omit Pi's --approve flag and approve individual local tool calls manually",
    )
    args = parser.parse_args(argv)

    pi = os.environ.get("PI_BIN", "pi")
    if not shutil.which(pi) and not Path(pi).is_file():
        parser.error(f"Pi executable not found: {pi!r}")
    if not TASK.is_file() or not SKILL.is_dir():
        parser.error("committed task contract or procesio-cli skill is missing")

    model = str(args.model).strip()
    thinking = str(args.thinking).strip()
    if "/" not in model:
        parser.error("--model must be an exact provider/model identifier")

    command = [
        pi,
        "-p",
        "--no-session",
        "--no-skills",
    ]
    if not args.interactive_approval:
        command.append("--approve")
    command += [
        "--model",
        model,
        "--models",
        model,
        "--thinking",
        thinking,
        "--skill",
        str(SKILL),
        "--",
        TASK.read_text(encoding="utf-8"),
    ]

    print("PROCESIO field trial: Evidence Status Normalizer", file=sys.stderr)
    print(f"Model: {model}; thinking: {thinking}", file=sys.stderr)
    print("Approved platform scope: one process create, one run, retain on success", file=sys.stderr)
    print("Target: pure-awesomeness / Internal-PROD / dc28053d-f701-4880-99c2-7d973899d135", file=sys.stderr)
    print(f"Contract: {TASK}", file=sys.stderr, flush=True)

    try:
        return subprocess.call(command, cwd=ROOT)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
