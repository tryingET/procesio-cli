#!/usr/bin/env -S uv run --script
#
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Run Control Tower Phase 06 through the original coordinator with a frozen skill.

The original coordinator metadata remains anchored to its original project inputs,
while the Pi execution receives the immutable full skill-package snapshot created by
the Phase 05 remediation wrapper. This prevents a later checkout from changing the
instructions used by a resumed final audit/export phase.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ORIGINAL = ROOT / "scripts" / "run-procesio-control-tower.py"
DEFAULT_RUN_ROOT = ROOT / "scratchpad" / "procesio-control-tower-v1"
DEFAULT_SKILL_ROOT = (
    DEFAULT_RUN_ROOT
    / "remediation"
    / "phase05"
    / "frozen-skill"
    / "procesio-cli"
)
CONFIRMATION = "FINISH_PROCESIO_CONTROL_TOWER_V1_PHASE06"
ORIGINAL_CONFIRMATION = "BUILD_PROCESIO_CONTROL_TOWER_V1"
PHASE06_ID = "06-export-audit-and-acceptance"


def _load_original():
    spec = importlib.util.spec_from_file_location(
        "run_procesio_control_tower_original", ORIGINAL
    )
    if spec is None or spec.loader is None:
        raise ValueError(f"cannot import original coordinator: {ORIGINAL}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _install_execution_skill(module, skill_root: Path) -> None:
    """Use ``skill_root`` for prompts/Pi while preserving old metadata identity."""
    original_skill = module.SKILL
    original_metadata_value = module._metadata_value

    if not (skill_root / "SKILL.md").is_file():
        raise ValueError(f"frozen skill root is invalid: {skill_root}")
    if not (original_skill / "SKILL.md").is_file():
        raise ValueError(f"original skill root is invalid: {original_skill}")

    def metadata_value(model: str, thinking: str):
        active = module.SKILL
        module.SKILL = original_skill
        try:
            return original_metadata_value(model, thinking)
        finally:
            module.SKILL = active

    def required_files():
        return (
            module.CONTRACT,
            module.MANIFEST,
            module.SEEDS,
            module.OPENAPI,
            original_skill / "SKILL.md",
            skill_root / "SKILL.md",
        )

    module._metadata_value = metadata_value
    module._required_files = required_files
    module.SKILL = skill_root


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--thinking", required=True)
    parser.add_argument("--run-root", type=Path, default=DEFAULT_RUN_ROOT)
    parser.add_argument("--skill-root", type=Path, default=DEFAULT_SKILL_ROOT)
    parser.add_argument("--max-hours", type=float, required=True)
    parser.add_argument("--confirm")
    parser.add_argument("--interactive-approval", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.confirm != CONFIRMATION:
        print(
            json.dumps(
                {
                    "error": {
                        "code": "confirmation_required",
                        "message": f"Pass --confirm {CONFIRMATION}.",
                        "details": {},
                    }
                },
                separators=(",", ":"),
            )
        )
        return 2
    if args.max_hours <= 0:
        print(
            json.dumps(
                {
                    "error": {
                        "code": "invalid_configuration",
                        "message": "--max-hours must be positive",
                        "details": {},
                    }
                },
                separators=(",", ":"),
            )
        )
        return 2

    try:
        run_root = args.run_root.expanduser().resolve()
        skill_root = args.skill_root.expanduser().resolve()
        module = _load_original()
        _install_execution_skill(module, skill_root)
    except (OSError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "error": {
                        "code": "frozen_phase06_setup_failed",
                        "message": str(exc),
                        "details": {},
                    }
                },
                separators=(",", ":"),
            )
        )
        return 2

    forwarded = [
        "--model",
        args.model,
        "--thinking",
        args.thinking,
        "--run-root",
        str(run_root),
        "--max-hours",
        str(args.max_hours),
        "--phase",
        PHASE06_ID,
        "--confirm",
        ORIGINAL_CONFIRMATION,
    ]
    if args.interactive_approval:
        forwarded.append("--interactive-approval")
    return int(module.main(forwarded))


if __name__ == "__main__":
    raise SystemExit(main())
