from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "pi-eval-preflight.py"
SPEC = importlib.util.spec_from_file_location("pi_eval_preflight", SCRIPT)
assert SPEC and SPEC.loader
PREFLIGHT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PREFLIGHT)


def test_quota_failure_is_not_reported_as_a_skill_failure():
    result = PREFLIGHT._classify_failure(
        'Warning: No models match pattern "workstation-inference/baseline-text"\n'
        '429: {"code":"1310","message":"Weekly/Monthly Limit Exhausted. '
        'Your limit will reset at 2026-09-04 23:41:13"}'
    )

    assert result["ready"] is False
    assert result["failure_class"] == "quota_exhausted"
    assert result["reset_at"] == "2026-09-04 23:41:13"
    assert result["unmatched_model_patterns"] == [
        "workstation-inference/baseline-text"
    ]
    assert "not a skill failure" in result["diagnosis"].lower()
    assert "PI_EVAL_MODEL" in result["next_action"]


def test_unmatched_model_pattern_has_a_specific_recovery_action():
    result = PREFLIGHT._classify_failure(
        'Warning: No models match pattern "workstation-inference/missing"'
    )

    assert result["failure_class"] == "model_not_available"
    assert result["unmatched_model_patterns"] == [
        "workstation-inference/missing"
    ]
    assert "pi --list-models" in result["next_action"]


def test_preflight_command_is_pinned_ephemeral_tool_free_and_scope_overridden():
    command = PREFLIGHT._command(
        "pi",
        model="provider/model-id",
        provider=None,
        thinking="low",
    )

    assert command[0] == "pi"
    assert command[command.index("--model") + 1] == "provider/model-id"
    assert command[command.index("--models") + 1] == "provider/model-id"
    assert command[command.index("--thinking") + 1] == "low"
    assert "--no-session" in command
    assert "--no-tools" in command
    assert "--no-skills" in command
    assert "--no-context-files" in command
    assert command[-1] == "Reply with exactly: PI_EVAL_OK"


def test_separate_provider_uses_unqualified_model_and_canonical_scope():
    command = PREFLIGHT._command(
        "pi",
        model="provider/model-id",
        provider="provider",
        thinking=None,
    )

    assert command[command.index("--provider") + 1] == "provider"
    assert command[command.index("--model") + 1] == "model-id"
    assert command[command.index("--models") + 1] == "provider/model-id"


def test_separate_provider_qualifies_an_unqualified_model_scope():
    command = PREFLIGHT._command(
        "pi",
        model="model-id",
        provider="provider",
        thinking=None,
    )

    assert command[command.index("--model") + 1] == "model-id"
    assert command[command.index("--models") + 1] == "provider/model-id"
