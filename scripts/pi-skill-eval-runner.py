#!/usr/bin/env python3
"""Use Pi's existing local login as a behavioral skill-evaluation runner.

The parent harness sends one JSON request on stdin. This adapter copies the
selected skill corpus to a neutral temporary path, starts a fresh non-interactive
Pi context with only read-only file tools, and asks it to select a skill and answer
the task. A second fresh Pi context judges the response against the hidden
expected-output guidance. Exactly one JSON object is printed on stdout.

No provider token is accepted by this script. Pi resolves its already configured
local login from its normal auth store.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable

_ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_NAME_RE = re.compile(r"^name:\s*['\"]?([^'\"\n]+)['\"]?\s*$", re.MULTILINE)

_AGENT_SYSTEM = """You are running one blinded Agent Skills behavior evaluation.
Only the explicitly loaded skills are available. You may use read, grep, find,
and ls only to inspect those skill files. Do not execute the user's requested
operation, access a network service, mutate files, or mention evaluation mechanics.
Select at most one relevant skill, inspect that skill's full SKILL.md before
answering, and answer the user as the skill directs. If no loaded skill applies,
select null and answer without pretending one applies.
Your final output must be exactly one JSON object with these fields:
{"selected_skill":"an exact loaded skill name or null","response":"the assistant answer"}
Do not use Markdown fences around the JSON.
"""

_JUDGE_SYSTEM = """You are an independent, strict response evaluator. Judge only
whether the candidate response substantively satisfies the supplied behavioral
criteria for the user task. Do not reward parroting, unsupported claims, unsafe
actions, or vague promises. Return exactly one JSON object:
{"task_success":true_or_false,"assertion_results":{"short_snake_case_check":true_or_false},"rationale":"brief explanation"}
Use several concrete assertion checks derived from the criteria. Do not use
Markdown fences around the JSON.
"""


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text or "").strip()


def _extract_json_object(text: str) -> dict[str, Any]:
    """Parse a JSON object even when a model wrapped it in a code fence or prose."""
    clean = _strip_ansi(text)
    if clean.startswith("```") and clean.endswith("```"):
        lines = clean.splitlines()
        if len(lines) >= 3:
            clean = "\n".join(lines[1:-1]).strip()
    try:
        value = json.loads(clean)
        if isinstance(value, dict):
            return value
    except json.JSONDecodeError:
        pass

    decoder = json.JSONDecoder()
    for index, char in enumerate(clean):
        if char != "{":
            continue
        try:
            value, _end = decoder.raw_decode(clean[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise ValueError("Pi did not return a JSON object")


def _skill_name(skill_md: Path) -> str:
    text = skill_md.read_text(encoding="utf-8")
    match = _NAME_RE.search(text)
    if not match:
        raise ValueError(f"skill has no simple frontmatter name: {skill_md}")
    return match.group(1).strip()


def _discover_skills(root: Path) -> list[tuple[str, Path]]:
    found: list[tuple[str, Path]] = []
    for skill_md in sorted(root.rglob("SKILL.md")):
        found.append((_skill_name(skill_md), skill_md.parent))
    if not found:
        raise ValueError(f"no SKILL.md files found under {root}")
    names = [name for name, _path in found]
    if len(names) != len(set(names)):
        raise ValueError(f"duplicate skill names in corpus: {names}")
    return found


def _reject_symlinks(root: Path) -> None:
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ValueError(f"skill corpus contains a symlink: {path}")


def _split_extra_args(value: str) -> list[str]:
    if not value.strip():
        return []
    if os.name != "nt":
        return shlex.split(value)
    tokens = shlex.split(value, posix=False)
    return [
        token[1:-1]
        if len(token) >= 2 and token[0] == token[-1] and token[0] in {'"', "'"}
        else token
        for token in tokens
    ]


def _pi_base_command(*, skill_dirs: list[Path], read_only_tools: bool,
                     system_prompt: str) -> list[str]:
    binary = os.environ.get("PI_BIN", "pi")
    if not shutil.which(binary) and not Path(binary).is_file():
        raise FileNotFoundError(
            f"Pi executable not found: {binary!r}. Install Pi or set PI_BIN."
        )

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
    ]
    if read_only_tools:
        command += ["--tools", "read,grep,find,ls"]
    else:
        command += ["--no-tools"]

    provider = os.environ.get("PI_EVAL_PROVIDER")
    model = os.environ.get("PI_EVAL_MODEL")
    thinking = os.environ.get("PI_EVAL_THINKING")
    if provider:
        command += ["--provider", provider]
    if model:
        command += ["--model", model]
    if thinking:
        command += ["--thinking", thinking]
    command += _split_extra_args(os.environ.get("PI_EVAL_EXTRA_ARGS", ""))

    for directory in skill_dirs:
        command += ["--skill", str(directory)]
    # Replace, rather than append to, any user-level custom system prompt so the
    # A/A and A/B runs differ only by the supplied skill corpus.
    command += ["--system-prompt", system_prompt]
    return command


def _invoke_pi(*, prompt: str, cwd: Path, skill_dirs: list[Path],
               read_only_tools: bool, system_prompt: str) -> tuple[dict[str, Any], str]:
    command = _pi_base_command(
        skill_dirs=skill_dirs,
        read_only_tools=read_only_tools,
        system_prompt=system_prompt,
    )
    timeout = int(os.environ.get("PI_EVAL_CALL_TIMEOUT", "600"))
    process = subprocess.run(
        [*command, "--", prompt],
        cwd=cwd,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    stderr = _strip_ansi(process.stderr)
    if process.returncode:
        detail = stderr or _strip_ansi(process.stdout)
        raise RuntimeError(f"Pi exited {process.returncode}: {detail[:2000]}")
    return _extract_json_object(process.stdout), stderr


def _response_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def evaluate_request(
    request: dict[str, Any],
    *,
    invoke: Callable[..., tuple[dict[str, Any], str]] = _invoke_pi,
) -> dict[str, Any]:
    root = Path(str(request.get("skills_root") or "")).expanduser().resolve()
    task = str(request.get("task") or "").strip()
    expected = str(request.get("expected_output") or "").strip()
    if not root.is_dir():
        raise ValueError(f"skills_root is not a directory: {root}")
    if not task:
        raise ValueError("task is required")
    if not expected:
        raise ValueError("expected_output is required for independent judging")
    _reject_symlinks(root)

    with tempfile.TemporaryDirectory(prefix="pi-skill-eval-") as temporary:
        temp_root = Path(temporary)
        neutral_root = temp_root / "corpus"
        shutil.copytree(root, neutral_root)
        skills = _discover_skills(neutral_root)
        known_names = [name for name, _path in skills]
        work = temp_root / "work"
        work.mkdir()

        agent_prompt = (
            "Loaded skill names:\n- " + "\n- ".join(known_names) +
            "\n\nUser task:\n" + task
        )
        agent, agent_stderr = invoke(
            prompt=agent_prompt,
            cwd=work,
            skill_dirs=[path for _name, path in skills],
            read_only_tools=True,
            system_prompt=_AGENT_SYSTEM,
        )
        selected = agent.get("selected_skill")
        if isinstance(selected, str):
            selected = selected.strip()
            if selected.startswith("/skill:"):
                selected = selected.removeprefix("/skill:").split()[0]
            if selected.lower() in {"none", "null", "n/a", ""}:
                selected = None
        elif selected is not None:
            selected = str(selected)
        response = _response_text(agent.get("response", ""))
        if not response.strip():
            raise ValueError("Pi agent returned an empty response")

        judge_prompt = json.dumps(
            {
                "user_task": task,
                "behavioral_criteria": expected,
                "candidate_response": response,
            },
            ensure_ascii=False,
            indent=2,
        )
        judge, judge_stderr = invoke(
            prompt=judge_prompt,
            cwd=work,
            skill_dirs=[],
            read_only_tools=False,
            system_prompt=_JUDGE_SYSTEM,
        )
        assertions = judge.get("assertion_results")
        if not isinstance(assertions, dict):
            assertions = {"judge_returned_assertions": False}
        else:
            assertions = {str(k): bool(v) for k, v in assertions.items()}
        task_success = bool(judge.get("task_success")) and all(assertions.values())

        warnings: list[str] = []
        if selected is not None and selected not in known_names:
            warnings.append(
                f"selected_skill {selected!r} is not one of the loaded skill names"
            )
        stderr_parts = [part for part in (agent_stderr, judge_stderr) if part]
        if stderr_parts:
            print("\n".join(stderr_parts)[:4000], file=sys.stderr)

        result: dict[str, Any] = {
            "selected_skill": selected,
            "task_success": task_success,
            "response": response,
            "assertion_results": assertions,
            "judge_rationale": _response_text(judge.get("rationale", "")),
            "total_tokens": None,
        }
        if warnings:
            result["runner_warnings"] = warnings
        return result


def main() -> int:
    try:
        raw = sys.stdin.read()
        request = json.loads(raw)
        if not isinstance(request, dict):
            raise ValueError("stdin must contain one JSON object")
        result = evaluate_request(request)
    except Exception as exc:  # noqa: BLE001 - runner must surface one actionable failure
        print(f"pi-skill-eval-runner: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
