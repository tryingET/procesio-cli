from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "pi-skill-eval-runner.py"
SPEC = importlib.util.spec_from_file_location("pi_skill_eval_runner", SCRIPT)
assert SPEC and SPEC.loader
RUNNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNNER)


def test_extract_json_object_accepts_fenced_or_prefixed_output():
    assert RUNNER._extract_json_object('```json\n{"ok":true}\n```') == {"ok": True}
    assert RUNNER._extract_json_object('note\n{"ok":true}\ntrailing') == {"ok": True}


def test_evaluate_request_uses_neutral_corpus_and_independent_judge(tmp_path):
    source = tmp_path / "candidate-skills"
    skill = source / "example-skill"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: example-skill\ndescription: Example skill.\n---\n\n# Example\n",
        encoding="utf-8",
    )

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
    skill = source / "example-skill"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: example-skill\ndescription: Example skill.\n---\n",
        encoding="utf-8",
    )

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


def test_pi_command_is_ephemeral_isolated_and_read_only(monkeypatch, tmp_path):
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
    assert command[command.index("--thinking") + 1] == "low"
