from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "pi-skill-eval-runner.py"
SPEC = importlib.util.spec_from_file_location("pi_skill_eval_runner", SCRIPT)
assert SPEC and SPEC.loader
RUNNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNNER)


def _write_example_skill(root: Path) -> None:
    skill = root / "example-skill"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: example-skill\ndescription: Example skill.\n---\n\n# Example\n",
        encoding="utf-8",
    )


def test_extract_json_object_accepts_fenced_or_prefixed_output():
    assert RUNNER._extract_json_object('```json\n{"ok":true}\n```') == {"ok": True}
    assert RUNNER._extract_json_object('note\n{"ok":true}\ntrailing') == {"ok": True}


def test_evaluate_request_uses_neutral_corpus_and_independent_judge(tmp_path):
    source = tmp_path / "candidate-skills"
    _write_example_skill(source)
    calls = []

    def fake_invoke(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return {
                "selected_skill": "/skill:example-skill",
                "response": "Use the safe workflow.",
            }, ""
        return {
            "task_success": True,
            "assertion_results": {
                "uses_safe_workflow": True,
                "is_actionable": True,
            },
            "rationale": "Meets both criteria.",
        }, ""

    result = RUNNER.evaluate_request(
        {
            "skills_root": str(source),
            "task": "Handle this request safely.",
            "expected_output": "Use a safe, actionable workflow.",
        },
        invoke=fake_invoke,
    )

    assert result["selected_skill"] == "example-skill"
    assert result["task_success"] is True
    assert result["assertion_results"] == {
        "uses_safe_workflow": True,
        "is_actionable": True,
    }
    assert len(calls) == 2
    assert calls[0]["read_only_tools"] is True
    assert calls[1]["read_only_tools"] is False
    assert calls[1]["skill_dirs"] == []
    assert all("candidate-skills" not in str(path) for path in calls[0]["skill_dirs"])


def test_failed_judge_assertion_fails_task_success(tmp_path):
    source = tmp_path / "skills"
    _write_example_skill(source)
    outputs = iter([
        ({"selected_skill": "example-skill", "response": "Partial answer."}, ""),
        ({
            "task_success": True,
            "assertion_results": {"safe": True, "complete": False},
            "rationale": "Incomplete.",
        }, ""),
    ])

    result = RUNNER.evaluate_request(
        {
            "skills_root": str(source),
            "task": "Do the task.",
            "expected_output": "Be safe and complete.",
        },
        invoke=lambda **_kwargs: next(outputs),
    )

    assert result["task_success"] is False


def test_string_booleans_are_not_accepted_as_passing_grades(tmp_path):
    source = tmp_path / "skills"
    _write_example_skill(source)
    outputs = iter([
        ({"selected_skill": "example-skill", "response": "Answer."}, ""),
        ({
            "task_success": "true",
            "assertion_results": {"safe": "true"},
            "rationale": "Malformed booleans.",
        }, ""),
    ])

    result = RUNNER.evaluate_request(
        {
            "skills_root": str(source),
            "task": "Do the task.",
            "expected_output": "Be safe.",
        },
        invoke=lambda **_kwargs: next(outputs),
    )

    assert result["task_success"] is False
    assert result["assertion_results"] == {"safe": False}


def test_pi_command_is_ephemeral_isolated_read_only_and_model_pinned(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(RUNNER.shutil, "which", lambda _binary: "/usr/bin/pi")
    monkeypatch.setenv("PI_EVAL_PROVIDER", "openai")
    monkeypatch.setenv("PI_EVAL_MODEL", "test-model")
    monkeypatch.setenv("PI_EVAL_THINKING", "low")

    command = RUNNER._pi_base_command(
        skill_dirs=[tmp_path / "skill"],
        read_only_tools=True,
        system_prompt="test system",
    )

    assert command[0] == "pi"
    assert "--no-session" in command
    assert "--no-context-files" in command
    assert "--no-extensions" in command
    assert "--no-skills" in command
    assert command[command.index("--tools") + 1] == "read,grep,find,ls"
    assert "bash" not in command and "write" not in command and "edit" not in command
    assert command[command.index("--provider") + 1] == "openai"
    assert command[command.index("--model") + 1] == "test-model"
    assert command[command.index("--models") + 1] == "openai/test-model"
    assert command[command.index("--thinking") + 1] == "low"
    assert command[command.index("--system-prompt") + 1] == "test system"
    assert "--append-system-prompt" not in command


def test_pi_model_must_be_explicitly_pinned(monkeypatch, tmp_path):
    monkeypatch.setattr(RUNNER.shutil, "which", lambda _binary: "/usr/bin/pi")
    monkeypatch.delenv("PI_EVAL_PROVIDER", raising=False)
    monkeypatch.delenv("PI_EVAL_MODEL", raising=False)

    with pytest.raises(RUNNER.PiRunnerError) as caught:
        RUNNER._pi_base_command(
            skill_dirs=[tmp_path / "skill"],
            read_only_tools=True,
            system_prompt="test system",
        )

    assert caught.value.code == "model_not_pinned"
    assert "PI_EVAL_MODEL" in caught.value.message


def test_canonical_model_id_overrides_ambient_enabled_models(monkeypatch, tmp_path):
    monkeypatch.setattr(RUNNER.shutil, "which", lambda _binary: "/usr/bin/pi")
    monkeypatch.delenv("PI_EVAL_PROVIDER", raising=False)
    monkeypatch.setenv("PI_EVAL_MODEL", "another-provider/working-model")
    monkeypatch.delenv("PI_EVAL_THINKING", raising=False)

    command = RUNNER._pi_base_command(
        skill_dirs=[tmp_path / "skill"],
        read_only_tools=False,
        system_prompt="judge",
    )

    assert "--provider" not in command
    assert command[command.index("--model") + 1] == "another-provider/working-model"
    assert command[command.index("--models") + 1] == "another-provider/working-model"
    assert "--no-tools" in command


def test_quota_exhaustion_is_classified_with_reset_and_stale_patterns(monkeypatch):
    monkeypatch.setenv(
        "PI_EVAL_MODEL",
        "workstation-inference/baseline-text",
    )
    error = RUNNER._classify_pi_failure(
        """
        Warning: No models match pattern "workstation-inference/baseline-text"
        Warning: No models match pattern "workstation-inference/baseline-text-mtp"
        429: {"code":"1310","message":"Weekly/Monthly Limit Exhausted.
        Your limit will reset at 2026-09-04 23:41:13"}
        """,
        returncode=1,
    )

    assert error.code == "model_quota_exhausted"
    assert error.reset_at == "2026-09-04 23:41:13"
    assert error.model == "workstation-inference/baseline-text"
    assert error.unmatched_model_patterns == [
        "workstation-inference/baseline-text",
        "workstation-inference/baseline-text-mtp",
    ]
    public = error.public_result()["runner_error"]
    assert public["code"] == "model_quota_exhausted"
    assert "different logged-in model" in public["next_action"]


def test_unmatched_explicit_model_is_classified_separately(monkeypatch):
    monkeypatch.setenv("PI_EVAL_MODEL", "missing/provider-model")
    error = RUNNER._classify_pi_failure(
        'Warning: No models match pattern "missing/provider-model"',
        returncode=1,
    )

    assert error.code == "model_not_available"
    assert error.unmatched_model_patterns == ["missing/provider-model"]
