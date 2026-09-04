#!/usr/bin/env -S uv run --script
#
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""PEP 723 uv entry point for the canonical checkpointed Gate 5 series runner.

Use either:

    uv run --script scripts/run-local-pi-gate5-overnight.py --help

or execute this file directly after making it executable. All implementation,
checkpointing, fixed-jury validation, phase gating, quota backoff, and status
reporting remain in ``run-local-pi-gate5-series-unattended.py`` so there is one
source of truth.
"""
from __future__ import annotations

import runpy
from pathlib import Path

TARGET = Path(__file__).with_name("run-local-pi-gate5-series-unattended.py")
if not TARGET.is_file():
    raise SystemExit(f"canonical Gate 5 runner is missing: {TARGET}")

runpy.run_path(str(TARGET), run_name="__main__")
