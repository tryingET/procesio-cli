#!/usr/bin/env python3
"""Verify one explicitly selected Pi model before running skill evaluations.

This is intentionally separate from the skill evaluator. It makes exactly one
no-tools, no-session Pi call and classifies model-selection or provider-quota
failures without misreporting them as skill failures.

Use a full model identifier from ``pi --list-models`` whenever possible:

    uv run python scripts/pi-eval-preflight.py --model provider/model-id

The preflight passes both ``--model`` and an exact ``--models`` scope. The latter
overrides stale user-level ``enabledModels`` patterns, matching the behavioral
runner's model-selection contract. The script never reads or prints Pi
credentials.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

_ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_RESET_RE = re.compile(
    r"reset\s+at\s+([0-9]{4}-[0-9]{2}-[0-9]{2}\s+[0-9]{2}:[0-9]{2}:[0-9]{2})",
    re.IGNORECASE,
)
_MODEL_PATTERN_RE = re.compile(r'No models match pattern\s+"([^"]+)"', re.IGNORECASE)
_MARKER = "PI_EVAL_OK"


def _clean(text: str | None) -> str:
    return _ANSI_RE.sub("", text or "").strip()


def _classify_failure(stderr: str, stdout: str = "") -> dict:
    """Return a non-secret, machine-readable provider failure classification."""
    detail = _clean(stderr or stdout)
    lowered = detail.lower()
    stale_patterns = sorted(set(_MODEL_PATTERN_RE.findall(detail)))
    reset = _RESET_RE.search(detail)

    common: dict = {"ready": False}
    if stale_patterns:
        common["unmatched_model_patterns"] = stale_patterns

    if "weekly/monthly limit exhausted" in lowered or (
        "429" in lowered and ("limit" in lowered or "quota" in lowered)
    ):
        common.update(
            {
                "failure_class": "quota_exhausted",
                "reset_at": reset.group(1) if reset else None,
                "diagnosis": (
                    "The selected model provider rejected the call before any skill "
                    "evaluation began. This is not a skill failure."
                ),
                "next_action": (
                    "Select a different exact Pi model with available quota, or retry "
                    "after the provider-reported reset. Keep PI_EVAL_MODEL pinned for "
                    "the subsequent evaluation."
                ),
            }
        )
        return common

    if "no models match pattern" in lowered or "model not found" in lowered:
        common.update(
            {
                "failure_class": "model_not_available",
                "diagnosis": (
                    "Pi could not resolve the requested or globally scoped model. No "
                    "skill evaluation began."
                ),
                "next_action": (
                    "Run `pi --list-models`, choose an exact available provider/model "
                    "identifier, and pass it with --model and PI_EVAL_MODEL."
                ),
            }
        )
        return common

    common.update(
        {
            "failure_class": "pi_provider_error",
            "diagnosis": "Pi exited before the skill evaluation could begin.",
            "next_action": (
                "Test the exact model with this preflight and inspect Pi login/provider "
                "state. Do not change skill code based on this failure."
            ),
        }
    )
    return common


def _model_selection(model: str, provider: str | None) -> tuple[str, str]:
    """Return the CLI model value and exact scoped-model pattern.

    When ``provider`` is supplied separately, Pi expects the unqualified model ID
    for ``--model`` while ``--models`` still needs the canonical provider/model
    pattern. Without a separate provider, the full configured identifier is valid
    for both flags.
    """
    configured = model.strip()
    selected_provider = (provider or "").strip() or None
    cli_model = configured
    if selected_provider and configured.lower().startswith(selected_provider.lower() + "/"):
        cli_model = configured[len(selected_provider) + 1 :]
    scope_pattern = (
        configured
        if not selected_provider or configured.lower().startswith(selected_provider.lower() + "/")
        else f"{selected_provider}/{configured}"
    )
    return cli_model, scope_pattern


def _command(binary: str, *, model: str, provider: str | None,
             thinking: str | None) -> list[str]:
    cli_model, scope_pattern = _model_selection(model, provider)
    command = [
        binary,
        "-p",
        "--no-session",
        "--approve",
        "--no-context-files",
        "--no-extensions",
        "--no-prompt-templates",
        "--no-themes",
        "--no-skills",
        "--no-tools",
    ]
    if provider:
        command += ["--provider", provider]
    command += ["--model", cli_model, "--models", scope_pattern]
    if thinking:
        command += ["--thinking", thinking]
    command += ["--", f"Reply with exactly: {_MARKER}"]
    return command


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model",
        default=os.environ.get("PI_EVAL_MODEL"),
        help="exact Pi model identifier; defaults to PI_EVAL_MODEL",
    )
    parser.add_argument(
        "--provider",
        default=os.environ.get("PI_EVAL_PROVIDER"),
        help="optional provider override; defaults to PI_EVAL_PROVIDER",
    )
    parser.add_argument(
        "--thinking",
        default=os.environ.get("PI_EVAL_THINKING"),
        help="optional thinking level; defaults to PI_EVAL_THINKING",
    )
    parser.add_argument("--timeout", type=int, default=120)
    args = parser.parse_args(argv)

    if not args.model:
        parser.error(
            "--model or PI_EVAL_MODEL is required. Run `pi --list-models` and "
            "choose an exact provider/model identifier."
        )

    binary = os.environ.get("PI_BIN", "pi")
    if not shutil.which(binary) and not Path(binary).is_file():
        print(
            json.dumps(
                {
                    "ready": False,
                    "failure_class": "pi_not_found",
                    "diagnosis": f"Pi executable not found: {binary!r}",
                    "next_action": "Install Pi or set PI_BIN to its executable path.",
                },
                sort_keys=True,
            )
        )
        return 2

    try:
        process = subprocess.run(
            _command(
                binary,
                model=args.model,
                provider=args.provider,
                thinking=args.thinking,
            ),
            text=True,
            capture_output=True,
            timeout=args.timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        print(
            json.dumps(
                {
                    "ready": False,
                    "failure_class": "preflight_timeout",
                    "model": args.model,
                    "diagnosis": "The one-call Pi model preflight timed out.",
                    "next_action": "Check the selected provider/model and retry the preflight.",
                },
                sort_keys=True,
            )
        )
        return 2

    if process.returncode:
        result = _classify_failure(process.stderr, process.stdout)
        result["model"] = args.model
        if args.provider:
            result["provider"] = args.provider
        print(json.dumps(result, sort_keys=True))
        return 2

    stdout = _clean(process.stdout)
    warnings = sorted(set(_MODEL_PATTERN_RE.findall(_clean(process.stderr))))
    ready = _MARKER in stdout
    result: dict = {
        "ready": ready,
        "model": args.model,
        "provider": args.provider,
        "marker_seen": ready,
    }
    if warnings:
        result["unmatched_model_patterns"] = warnings
    if not ready:
        result.update(
            {
                "failure_class": "unexpected_model_response",
                "diagnosis": "Pi answered, but the expected preflight marker was absent.",
                "next_action": "Choose a normal text-generation model and retry.",
            }
        )
    print(json.dumps(result, sort_keys=True))
    return 0 if ready else 2


if __name__ == "__main__":
    raise SystemExit(main())
