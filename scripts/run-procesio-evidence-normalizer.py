#!/usr/bin/env -S uv run --script
#
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Run the retained PROCESIO Evidence Status Normalizer exactly once.

Input is one status JSON object from stdin, ``--input FILE``, or ``--json``.
The script checks authentication, runs the retained process synchronously once,
reads that instance's output, and prints one JSON object. It never retries a
timed-out or ambiguous write.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator

ROOT = Path(__file__).resolve().parents[1]
RUN_TOOL = ROOT / "scripts" / "run-tool.py"
DEFAULT_DEPLOYMENT = (
    ROOT / "examples" / "procesio" / "evidence-status-normalizer.deployment.json"
)


@dataclass(frozen=True)
class Call:
    code: int
    data: dict[str, Any] | None
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False


Runner = Callable[[list[str], float], Call]


def _json_object(text: str, label: str) -> dict[str, Any]:
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} is not valid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _emit(value: dict[str, Any]) -> None:
    print(json.dumps(value, ensure_ascii=False, separators=(",", ":")))


def _walk(value: Any) -> Iterator[Any]:
    yield value
    if isinstance(value, dict):
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _ci(mapping: dict[str, Any], *names: str) -> Any:
    wanted = {name.casefold() for name in names}
    for key, value in mapping.items():
        if str(key).casefold() in wanted:
            return value
    return None


def _first(value: Any, *names: str) -> Any:
    wanted = {name.casefold() for name in names}
    for item in _walk(value):
        if isinstance(item, dict):
            for key, child in item.items():
                if str(key).casefold() in wanted and child not in (None, ""):
                    return child
    return None


def _decode(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return value
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return value


def _status_code(value: Any) -> Any:
    try:
        return int(value)
    except (TypeError, ValueError):
        return value


def _variable(value: Any, name: str) -> Any:
    target = name.casefold()
    for item in _walk(value):
        if isinstance(item, dict):
            for key, child in item.items():
                if str(key).casefold() == target:
                    return _decode(child)
    for item in _walk(value):
        if not isinstance(item, dict):
            continue
        actual = _ci(item, "name", "variableName", "displayName", "key")
        if isinstance(actual, str) and actual.casefold() == target:
            return _decode(
                _ci(item, "value", "variableValue", "data", "result", "defaultValue")
            )
    return None


def _tool_error(data: dict[str, Any] | None) -> str | None:
    error = data.get("error") if isinstance(data, dict) else None
    return error.get("code") if isinstance(error, dict) else None


def _call_tool(argv: list[str], timeout: float) -> Call:
    command = [
        os.environ.get("UV_BIN", "uv"),
        "run",
        "python",
        str(RUN_TOOL),
        "procesio",
        *argv,
    ]
    try:
        proc = subprocess.run(
            command,
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode() if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        return Call(124, None, stdout, stderr, True)
    data = None
    try:
        parsed = json.loads(proc.stdout)
        if isinstance(parsed, dict):
            data = parsed
    except json.JSONDecodeError:
        pass
    return Call(proc.returncode, data, proc.stdout, proc.stderr)


def _ambiguous_run(call: Call) -> bool:
    if call.timed_out:
        return True
    text = " ".join(
        (
            call.stdout,
            call.stderr,
            json.dumps(call.data, ensure_ascii=False) if call.data else "",
        )
    ).casefold()
    return any(
        marker in text
        for marker in (
            "timed out",
            "timeout",
            "connection reset",
            "connection aborted",
            "connection closed",
            "broken pipe",
            "remote disconnected",
            "no response",
        )
    )


def _failure(code: str, message: str, **details: Any) -> tuple[int, dict[str, Any]]:
    return 1, {"error": {"code": code, "message": message, "details": details}}


def run_once(
    status: dict[str, Any],
    deployment: dict[str, Any],
    *,
    runner: Runner = _call_tool,
    timeout: int = 120,
    raw: bool = False,
) -> tuple[int, dict[str, Any]]:
    scope = [
        "--profile", deployment["profile"],
        "--environment", deployment["environment"],
        "--workspace-id", deployment["workspace_id"],
    ]
    process_id = deployment["process_id"]

    auth = runner(["check-auth", *scope], 90)
    if auth.code or not auth.data or auth.data.get("authenticated") is not True:
        return _failure(
            "authentication_failed",
            "Authentication did not pass; the process was not executed.",
            profile=deployment["profile"],
            environment=deployment["environment"],
            workspace_id=deployment["workspace_id"],
            result=auth.data,
        )

    run = runner(
        [
            "run-process", "--id", process_id,
            "--payload", json.dumps({"status": status}, separators=(",", ":")),
            "--synchronous", "--timeout", str(timeout),
            *scope,
        ],
        max(180, timeout + 90),
    )
    if run.code or not run.data:
        if _ambiguous_run(run):
            return _failure(
                "unknown_run_outcome",
                "The run outcome is unknown. Do not retry blindly; reconcile instances first.",
                process_id=process_id,
                retry_performed=False,
                tool_code=_tool_error(run.data),
            )
        return _failure(
            "run_failed",
            "PROCESIO did not return a successful run result.",
            process_id=process_id,
            retry_performed=False,
            tool_code=_tool_error(run.data),
            result=run.data,
        )

    run_result = run.data.get("result", run.data)
    instance_id = _first(run_result, "instanceId", "flowInstanceId", "instance_id")
    status_code = _status_code(_first(run_result, "status"))
    if instance_id is None:
        for item in _walk(run_result):
            if isinstance(item, dict) and _ci(item, "id") and _ci(item, "status") is not None:
                instance_id = _ci(item, "id")
                break
    if instance_id is None:
        return _failure(
            "unknown_run_outcome",
            "The run returned no stable instance ID. Reconcile instances before another run.",
            process_id=process_id,
            retry_performed=False,
        )

    output = runner(
        [
            "get-instance-output", "--id", str(instance_id),
            "--flow-template-id", process_id,
            *scope,
        ],
        90,
    )
    if output.code or not output.data:
        return _failure(
            "instance_output_unavailable",
            "The instance exists, but its output could not be read. Inspect it; do not rerun.",
            process_id=process_id,
            instance_id=str(instance_id),
            retry_performed=False,
            tool_code=_tool_error(output.data),
        )

    output_result = output.data.get("result", output.data)
    normalized = _variable(output_result, "normalized")
    script_error = _variable(output_result, "script_error")
    output_status = _first(output_result, "status")
    if output_status is not None:
        status_code = _status_code(output_status)
    ok = (
        status_code == 50
        and isinstance(normalized, dict)
        and script_error in (None, "", [], {})
    )
    result: dict[str, Any] = {
        "schema_version": 1,
        "ok": ok,
        "process_id": process_id,
        "instance_id": str(instance_id),
        "status": status_code,
        "normalized": normalized,
        "script_error": script_error,
        "executions_this_invocation": 1,
        "retry_performed": False,
    }
    if raw:
        result["raw"] = {"run": run.data, "output": output.data}
    if not ok:
        result["diagnosis"] = (
            "Expected status 50, a JSON normalized output, and an empty script_error. "
            "Inspect this instance before another run."
        )
    return (0 if ok else 1), result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--input", default="-", help="JSON file or '-' for stdin")
    source.add_argument("--json", help="status JSON object inline")
    parser.add_argument("--deployment", type=Path, default=DEFAULT_DEPLOYMENT)
    parser.add_argument("--profile")
    parser.add_argument("--environment")
    parser.add_argument("--workspace-id")
    parser.add_argument("--process-id")
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--raw", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.timeout < 1:
        _emit({"error": {"code": "invalid_input", "message": "--timeout must be positive", "details": {}}})
        return 2
    try:
        if args.json is not None:
            status = _json_object(args.json, "--json")
        elif args.input == "-":
            if sys.stdin.isatty():
                raise ValueError("pipe JSON on stdin or pass --input/--json")
            status = _json_object(sys.stdin.read(), "stdin")
        else:
            status = _json_object(Path(args.input).read_text(encoding="utf-8"), args.input)

        deployment = _json_object(
            args.deployment.expanduser().read_text(encoding="utf-8"),
            str(args.deployment),
        )
        for key, value in {
            "profile": args.profile,
            "environment": args.environment,
            "workspace_id": args.workspace_id,
            "process_id": args.process_id,
        }.items():
            if value:
                deployment[key] = value
        missing = [
            key for key in ("profile", "environment", "workspace_id", "process_id")
            if not isinstance(deployment.get(key), str) or not deployment[key]
        ]
        if missing:
            raise ValueError("deployment is missing: " + ", ".join(missing))
    except (OSError, ValueError) as exc:
        _emit({"error": {"code": "invalid_input", "message": str(exc), "details": {}}})
        return 2

    if args.dry_run:
        _emit({
            "schema_version": 1,
            "dry_run": True,
            "process_id": deployment["process_id"],
            "scope": {
                "profile": deployment["profile"],
                "environment": deployment["environment"],
                "workspace_id": deployment["workspace_id"],
            },
            "payload": {"status": status},
            "calls": ["check-auth", "run-process once", "get-instance-output"],
            "automatic_retries": 0,
        })
        return 0

    code, result = run_once(
        status, deployment, timeout=args.timeout, raw=args.raw
    )
    _emit(result)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
