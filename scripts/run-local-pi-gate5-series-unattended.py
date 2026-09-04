#!/usr/bin/env python3
"""Run the fixed-rubric Gate 5 series unattended for a bounded time.

A new run snapshots:

* the current candidate skill corpus,
* a byte-identical candidate control corpus for A/A,
* the frozen original skill corpus from ``--baseline-ref``, and
* the evaluator runtime used for every observation.

The coordinator then runs, in order:

1. A/A noise-floor evaluation;
2. blinded A/B round 1, only when A/A passes;
3. blinded A/B round 2, only when round 1 passes; and
4. deterministic series verification.

Every phase is checkpointed after each observation. Quota and rate-limit
interruptions trigger bounded exponential backoff. The run stops at the
wall-clock deadline, model-call cap, a failed gate, a non-retryable error, or
successful completion.

The evaluated model receives only read-only skill-file tools and never authenticates to or accesses PROCESIO.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
CURRENT_SKILLS = ROOT / "skills"
RUNTIME_FILES = (
    "pi-eval-preflight.py",
    "pi-skill-eval-runner.py",
    "pi-skill-eval-runner-strict.py",
    "run-skill-behavior-evals.py",
    "verify-skill-eval-series.py",
)
DEFAULT_BASELINE_REF = "da12de643c8a2355d019f40515766abf80a819df"
DEFAULT_PHASES = (
    ("aa", "aa", 20260902),
    ("ab-round-1", "ab", 20260903),
    ("ab-round-2", "ab", 20260904),
)
INCOMPLETE_EXIT = 75
_NAME_RE = re.compile(r"^name:\s*['\"]?([^'\"\n]+)['\"]?\s*$", re.MULTILINE)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return value


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fingerprint(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if path.is_symlink():
            raise ValueError(f"snapshot contains a symlink: {path}")
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _skill_names(root: Path) -> list[str]:
    names: list[str] = []
    for skill_md in sorted(root.glob("*/SKILL.md")):
        match = _NAME_RE.search(skill_md.read_text(encoding="utf-8"))
        if not match:
            raise ValueError(f"{skill_md}: missing simple frontmatter name")
        names.append(match.group(1).strip())
    if not names:
        raise ValueError(f"no top-level skills found under {root}")
    if len(names) != len(set(names)):
        raise ValueError(f"duplicate skill names under {root}: {names}")
    return names


def _git(args: list[str], *, text: bool = True) -> subprocess.CompletedProcess[Any]:
    process = subprocess.run(
        ["git", "-C", str(ROOT), *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=text,
        check=False,
    )
    if process.returncode:
        stderr = process.stderr if text else process.stderr.decode("utf-8", "replace")
        raise RuntimeError(f"git {' '.join(args)} failed: {stderr.strip()}")
    return process


def _resolve_ref(ref: str) -> str:
    return str(_git(["rev-parse", "--verify", f"{ref}^{{commit}}"]).stdout).strip()


def _export_git_subtree(ref: str, prefix: str, destination: Path) -> None:
    """Export tracked blobs below prefix without invoking a shell or extracting tar."""
    resolved = _resolve_ref(ref)
    listing = _git(
        ["ls-tree", "-r", "-z", "--full-tree", resolved, "--", prefix],
        text=False,
    ).stdout
    records = [record for record in listing.split(b"\0") if record]
    if not records:
        raise ValueError(f"{ref}: no tracked files below {prefix!r}")

    destination.mkdir(parents=True, exist_ok=False)
    prefix_path = PurePosixPath(prefix)
    for raw_record in records:
        metadata, separator, raw_path = raw_record.partition(b"\t")
        if not separator:
            raise ValueError("git ls-tree returned an unexpected record")
        fields = metadata.decode("ascii").split()
        if len(fields) != 3:
            raise ValueError("git ls-tree returned unexpected metadata")
        mode, object_type, object_sha = fields
        path_text = raw_path.decode("utf-8")
        posix = PurePosixPath(path_text)
        if (
            posix.is_absolute()
            or ".." in posix.parts
            or len(posix.parts) <= len(prefix_path.parts)
            or posix.parts[: len(prefix_path.parts)] != prefix_path.parts
        ):
            raise ValueError(f"unsafe git-tree path: {path_text!r}")
        if object_type != "blob" or mode == "120000":
            raise ValueError(f"unsupported git-tree entry {mode} {object_type}: {path_text}")

        blob = _git(["cat-file", "blob", object_sha], text=False).stdout
        target = destination.joinpath(*posix.parts[len(prefix_path.parts) :])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(blob)


def _copy_runtime(run_root: Path) -> dict[str, str]:
    runtime = run_root / "runtime"
    runtime.mkdir(parents=True, exist_ok=False)
    hashes: dict[str, str] = {}
    for name in RUNTIME_FILES:
        source = ROOT / "scripts" / name
        if not source.is_file():
            raise FileNotFoundError(source)
        target = runtime / name
        shutil.copy2(source, target)
        hashes[name] = _sha256_file(target)
    return hashes


def _phase_specs() -> list[dict[str, Any]]:
    return [
        {"id": phase_id, "mode": mode, "seed": seed}
        for phase_id, mode, seed in DEFAULT_PHASES
    ]


def _relative(run_root: Path, path: Path) -> str:
    return path.resolve().relative_to(run_root.resolve()).as_posix()


def _prepare_run(
    *,
    run_root: Path,
    baseline_ref: str,
    model: str,
    provider: str | None,
    thinking: str | None,
    repetitions: int,
) -> dict[str, Any]:
    if run_root.exists():
        if any(run_root.iterdir()):
            raise FileExistsError(
                f"{run_root} already exists without series-metadata.json; "
                "use an empty/new path or the exact prior run path"
            )
    else:
        run_root.mkdir(parents=True)

    snapshots = run_root / "snapshots"
    candidate = snapshots / "candidate" / "skills"
    control = snapshots / "control" / "skills"
    baseline = snapshots / "baseline" / "skills"
    candidate.parent.mkdir(parents=True)
    control.parent.mkdir(parents=True)
    baseline.parent.mkdir(parents=True)
    shutil.copytree(CURRENT_SKILLS, candidate)
    shutil.copytree(CURRENT_SKILLS, control)
    _export_git_subtree(baseline_ref, "skills", baseline)

    candidate_fingerprint = _fingerprint(candidate)
    control_fingerprint = _fingerprint(control)
    if candidate_fingerprint != control_fingerprint:
        raise ValueError("candidate and A/A control snapshots are not byte-identical")

    evals = candidate / "evals" / "behavioral.json"
    thresholds = candidate / "evals" / "gate5-thresholds.json"
    behavioral = _load_json(evals)
    threshold_values = _load_json(thresholds)
    suite_version = behavioral.get("suite_version")
    rubric_contract = behavioral.get("rubric_contract")
    cases = behavioral.get("cases")
    if not isinstance(suite_version, int) or suite_version < 3:
        raise ValueError("overnight series requires behavioral suite_version >= 3")
    if rubric_contract != "fixed-jury-rubric-v2":
        raise ValueError(
            "overnight series requires rubric_contract='fixed-jury-rubric-v2'"
        )
    if not isinstance(cases, list) or not cases:
        raise ValueError(f"{evals}: expected a non-empty cases list")
    minimum = int(threshold_values.get("minimum_repetitions", 5))
    if repetitions < minimum:
        raise ValueError(
            f"{repetitions} repetitions is below the registered minimum {minimum}"
        )

    runtime_hashes = _copy_runtime(run_root)
    candidate_commit = _resolve_ref("HEAD")
    baseline_commit = _resolve_ref(baseline_ref)
    per_phase = len(cases) * repetitions * 2
    phase_specs = _phase_specs()

    metadata: dict[str, Any] = {
        "schema_version": 1,
        "kind": "gate5-fixed-jury-series-metadata",
        "created_at": _utc_now(),
        "candidate_commit": candidate_commit,
        "baseline_ref": baseline_ref,
        "baseline_commit": baseline_commit,
        "model": model,
        "provider": provider,
        "thinking": thinking,
        "suite_version": suite_version,
        "rubric_contract": rubric_contract,
        "case_count": len(cases),
        "repetitions": repetitions,
        "observations_per_phase": per_phase,
        "total_observations": per_phase * len(phase_specs),
        "phase_order": phase_specs,
        "paths": {
            "candidate": _relative(run_root, candidate),
            "control": _relative(run_root, control),
            "baseline": _relative(run_root, baseline),
            "evals": _relative(run_root, evals),
            "thresholds": _relative(run_root, thresholds),
            "runtime": "runtime",
        },
        "skill_names": {
            "candidate": _skill_names(candidate),
            "baseline": _skill_names(baseline),
        },
        "fingerprints": {
            "candidate": candidate_fingerprint,
            "control": control_fingerprint,
            "baseline": _fingerprint(baseline),
            "evals_sha256": _sha256_file(evals),
            "thresholds_sha256": _sha256_file(thresholds),
            "runtime": runtime_hashes,
        },
    }
    _write_json(run_root / "series-metadata.json", metadata)
    _write_json(
        ROOT / "scratchpad" / "gate5-series-latest.json",
        {
            "schema_version": 1,
            "run_root": str(run_root.resolve()),
            "status_path": str((run_root / "series-status.json").resolve()),
            "metadata_path": str((run_root / "series-metadata.json").resolve()),
        },
    )
    return metadata


def _path_from_metadata(run_root: Path, metadata: dict[str, Any], key: str) -> Path:
    paths = metadata.get("paths")
    if not isinstance(paths, dict) or not isinstance(paths.get(key), str):
        raise ValueError(f"series metadata has no path for {key!r}")
    path = (run_root / paths[key]).resolve()
    try:
        path.relative_to(run_root.resolve())
    except ValueError as exc:
        raise ValueError(f"metadata path escapes run root: {key}") from exc
    return path


def _validate_run(run_root: Path, metadata: dict[str, Any]) -> None:
    if metadata.get("rubric_contract") != "fixed-jury-rubric-v2":
        raise ValueError("run does not use fixed-jury-rubric-v2")
    if int(metadata.get("suite_version") or 0) < 3:
        raise ValueError("run predates fixed-rubric suite v3")

    candidate = _path_from_metadata(run_root, metadata, "candidate")
    control = _path_from_metadata(run_root, metadata, "control")
    baseline = _path_from_metadata(run_root, metadata, "baseline")
    evals = _path_from_metadata(run_root, metadata, "evals")
    thresholds = _path_from_metadata(run_root, metadata, "thresholds")
    runtime = _path_from_metadata(run_root, metadata, "runtime")
    for path in (candidate, control, baseline, runtime):
        if not path.is_dir():
            raise FileNotFoundError(path)
    for path in (evals, thresholds):
        if not path.is_file():
            raise FileNotFoundError(path)

    fingerprints = metadata.get("fingerprints")
    if not isinstance(fingerprints, dict):
        raise ValueError("series metadata has no fingerprints")
    observed = {
        "candidate": _fingerprint(candidate),
        "control": _fingerprint(control),
        "baseline": _fingerprint(baseline),
        "evals_sha256": _sha256_file(evals),
        "thresholds_sha256": _sha256_file(thresholds),
    }
    for key, value in observed.items():
        if fingerprints.get(key) != value:
            raise ValueError(f"cannot resume: snapshot fingerprint changed for {key}")
    if observed["candidate"] != observed["control"]:
        raise ValueError("A/A candidate and control are no longer byte-identical")

    runtime_hashes = fingerprints.get("runtime")
    if not isinstance(runtime_hashes, dict):
        raise ValueError("series metadata has no runtime hashes")
    for name in RUNTIME_FILES:
        path = runtime / name
        if not path.is_file() or runtime_hashes.get(name) != _sha256_file(path):
            raise ValueError(f"cannot resume: frozen evaluator runtime changed: {name}")


def _load_or_prepare(
    *,
    run_root: Path,
    baseline_ref: str,
    model: str | None,
    provider: str | None,
    thinking: str | None,
    repetitions: int,
) -> tuple[dict[str, Any], str, str | None, str | None]:
    metadata_path = run_root / "series-metadata.json"
    if metadata_path.is_file():
        metadata = _load_json(metadata_path)
        _validate_run(run_root, metadata)
        locked_model = str(metadata.get("model") or "")
        locked_provider = (
            str(metadata["provider"]) if metadata.get("provider") else None
        )
        locked_thinking = (
            str(metadata["thinking"]) if metadata.get("thinking") else None
        )
        if model and model != locked_model:
            raise ValueError(
                f"cannot resume: model changed from {locked_model!r} to {model!r}"
            )
        if provider and provider != locked_provider:
            raise ValueError(
                f"cannot resume: provider changed from {locked_provider!r} to {provider!r}"
            )
        if thinking and thinking != locked_thinking:
            raise ValueError(
                f"cannot resume: thinking changed from {locked_thinking!r} to {thinking!r}"
            )
        if repetitions != int(metadata["repetitions"]):
            raise ValueError(
                "cannot resume: repetition count differs from frozen metadata"
            )
        return metadata, locked_model, locked_provider, locked_thinking

    if not model:
        raise ValueError(
            "PI_EVAL_MODEL or --model is required when creating a new series run"
        )
    metadata = _prepare_run(
        run_root=run_root,
        baseline_ref=baseline_ref,
        model=model,
        provider=provider,
        thinking=thinking,
        repetitions=repetitions,
    )
    return metadata, model, provider, thinking


def _jsonl_count(path: Path) -> int:
    if not path.is_file():
        return 0
    count = 0
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_number}: invalid JSON") from exc
        if not isinstance(value, dict):
            raise ValueError(f"{path}:{line_number}: expected an object")
        count += 1
    return count


def _phase_roots(
    run_root: Path,
    metadata: dict[str, Any],
    phase: dict[str, Any],
) -> tuple[Path, Path]:
    candidate = _path_from_metadata(run_root, metadata, "candidate")
    if phase["mode"] == "aa":
        return candidate, _path_from_metadata(run_root, metadata, "control")
    return candidate, _path_from_metadata(run_root, metadata, "baseline")


def _phase_state(
    run_root: Path,
    metadata: dict[str, Any],
    phase: dict[str, Any],
) -> dict[str, Any]:
    directory = run_root / "phases" / str(phase["id"])
    total = int(metadata["observations_per_phase"])
    completed = _jsonl_count(directory / "runs.jsonl")
    if completed > total:
        raise ValueError(f"{phase['id']}: checkpoint has {completed} rows; expected {total}")
    report_path = directory / "report.json"
    report = _load_json(report_path) if report_path.is_file() else None
    if report is not None and completed != total:
        raise ValueError(f"{phase['id']}: report exists before checkpoint completion")
    gate = report.get("gate") if isinstance(report, dict) else None
    return {
        "id": phase["id"],
        "mode": phase["mode"],
        "seed": int(phase["seed"]),
        "directory": directory,
        "runs_path": directory / "runs.jsonl",
        "report_path": report_path,
        "completed_observations": completed,
        "remaining_observations": total - completed,
        "total_observations": total,
        "gate": gate,
        "passed": bool(isinstance(gate, dict) and gate.get("passed") is True),
        "complete": report is not None,
    }


def _all_phase_states(
    run_root: Path, metadata: dict[str, Any]
) -> list[dict[str, Any]]:
    phases = metadata.get("phase_order")
    if not isinstance(phases, list) or len(phases) != 3:
        raise ValueError("series metadata must define exactly A/A and two A/B phases")
    return [_phase_state(run_root, metadata, phase) for phase in phases]


def _current_phase(states: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, str | None]:
    aa, ab1, ab2 = states
    if not aa["complete"]:
        return aa, None
    if not aa["passed"]:
        return None, "aa_noise_gate_failed"
    if not ab1["complete"]:
        return ab1, None
    if not ab1["passed"]:
        return None, "ab_round_1_failed"
    if not ab2["complete"]:
        return ab2, None
    if not ab2["passed"]:
        return None, "ab_round_2_failed"
    return None, "all_phases_passed"


def _parse_json_output(text: str) -> dict[str, Any]:
    clean = text.strip()
    if clean:
        try:
            value = json.loads(clean)
            if isinstance(value, dict):
                return value
        except json.JSONDecodeError:
            pass
    for line in reversed([item.strip() for item in clean.splitlines() if item.strip()]):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise ValueError("child command did not print a JSON object")


def _join_argv(argv: list[str]) -> str:
    return subprocess.list2cmdline(argv) if os.name == "nt" else shlex.join(argv)


def _invoke_preflight(
    *,
    runtime: Path,
    model: str,
    provider: str | None,
    thinking: str | None,
    timeout: int,
    env: dict[str, str],
) -> tuple[int, dict[str, Any]]:
    command = [
        sys.executable,
        str(runtime / "pi-eval-preflight.py"),
        "--model",
        model,
        "--timeout",
        str(timeout),
    ]
    if provider:
        command += ["--provider", provider]
    if thinking:
        command += ["--thinking", thinking]
    process = subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=None,
        check=False,
    )
    return int(process.returncode or 0), _parse_json_output(process.stdout)


def _invoke_phase_batch(
    *,
    run_root: Path,
    metadata: dict[str, Any],
    phase: dict[str, Any],
    observations: int,
    observation_timeout: int,
    env: dict[str, str],
    poll_seconds: float = 1.0,
) -> tuple[int, dict[str, Any]]:
    runtime = _path_from_metadata(run_root, metadata, "runtime")
    evals = _path_from_metadata(run_root, metadata, "evals")
    thresholds = _path_from_metadata(run_root, metadata, "thresholds")
    candidate, baseline = _phase_roots(run_root, metadata, phase)
    phase_dir = run_root / "phases" / str(phase["id"])
    phase_dir.mkdir(parents=True, exist_ok=True)
    runner = _join_argv([sys.executable, str(runtime / "pi-skill-eval-runner-strict.py")])
    command = [
        sys.executable,
        str(runtime / "run-skill-behavior-evals.py"),
        "--mode",
        str(phase["mode"]),
        "--candidate-root",
        str(candidate),
        "--baseline-root",
        str(baseline),
        "--evals",
        str(evals),
        "--thresholds",
        str(thresholds),
        "--runner",
        runner,
        "--workspace",
        str(phase_dir),
        "--repetitions",
        str(metadata["repetitions"]),
        "--seed",
        str(phase["seed"]),
        "--timeout",
        str(observation_timeout),
        "--max-new-observations",
        str(observations),
    ]
    if (phase_dir / "runs.jsonl").is_file():
        command.append("--resume")

    process = subprocess.Popen(
        command,
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=None,
    )
    shown = -1
    total = int(metadata["observations_per_phase"])
    while process.poll() is None:
        completed = _jsonl_count(phase_dir / "runs.jsonl")
        if completed != shown:
            print(
                f"[{phase['id']} {completed}/{total}] observations complete",
                file=sys.stderr,
                flush=True,
            )
            shown = completed
        time.sleep(poll_seconds)
    stdout, _ = process.communicate()
    completed = _jsonl_count(phase_dir / "runs.jsonl")
    if completed != shown:
        print(
            f"[{phase['id']} {completed}/{total}] observations complete",
            file=sys.stderr,
            flush=True,
        )
    return int(process.returncode or 0), _parse_json_output(stdout or "")


def _quota_or_rate_limited(value: dict[str, Any]) -> bool:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True).lower()
    return any(
        token in text
        for token in (
            "model_quota_exhausted",
            "quota_exhausted",
            "rate_limit",
            "rate limit",
            "limit exhausted",
            "too many requests",
        )
    )


def _runner_error(value: dict[str, Any]) -> bool:
    if isinstance(value.get("runner_error"), dict):
        return True
    interruption = value.get("interruption")
    return isinstance(interruption, dict) and isinstance(
        interruption.get("runner_error"), dict
    )


def _verify_series(run_root: Path, metadata: dict[str, Any]) -> dict[str, Any]:
    runtime = _path_from_metadata(run_root, metadata, "runtime")
    thresholds = _path_from_metadata(run_root, metadata, "thresholds")
    reports = [
        run_root / "phases" / "ab-round-1" / "report.json",
        run_root / "phases" / "ab-round-2" / "report.json",
    ]
    out = run_root / "series-report.json"
    command = [
        sys.executable,
        str(runtime / "verify-skill-eval-series.py"),
        *[str(path) for path in reports],
        "--thresholds",
        str(thresholds),
        "--out",
        str(out),
    ]
    process = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    result = _parse_json_output(process.stdout)
    if process.returncode and result.get("passed") is True:
        raise RuntimeError("series verifier exited nonzero despite a passing result")
    return result


def _status_payload(
    *,
    run_root: Path,
    metadata: dict[str, Any],
    started_at: str,
    status: str,
    stop_reason: str | None,
    current_phase: str | None,
    model_calls_upper_bound: int,
    max_model_calls: int,
    preflight_attempts: int,
    batch_attempts: int,
    last_result: dict[str, Any] | None,
    series_result: dict[str, Any] | None,
) -> dict[str, Any]:
    states = _all_phase_states(run_root, metadata)
    completed = sum(int(state["completed_observations"]) for state in states)
    total = sum(int(state["total_observations"]) for state in states)
    phases = []
    for state in states:
        phases.append(
            {
                "id": state["id"],
                "mode": state["mode"],
                "completed_observations": state["completed_observations"],
                "remaining_observations": state["remaining_observations"],
                "gate": state["gate"],
                "report_path": (
                    str(state["report_path"]) if state["report_path"].is_file() else None
                ),
            }
        )
    return {
        "schema_version": 1,
        "kind": "gate5-fixed-jury-series-status",
        "updated_at": _utc_now(),
        "started_at": started_at,
        "status": status,
        "stop_reason": stop_reason,
        "run_root": str(run_root),
        "suite_version": metadata["suite_version"],
        "rubric_contract": metadata["rubric_contract"],
        "model": metadata["model"],
        "provider": metadata.get("provider"),
        "thinking": metadata.get("thinking"),
        "candidate_commit": metadata["candidate_commit"],
        "baseline_commit": metadata["baseline_commit"],
        "current_phase": current_phase,
        "completed_observations": completed,
        "remaining_observations": total - completed,
        "total_observations": total,
        "model_calls_upper_bound_this_invocation": model_calls_upper_bound,
        "max_model_calls_this_invocation": max_model_calls,
        "preflight_attempts": preflight_attempts,
        "batch_attempts": batch_attempts,
        "phases": phases,
        "series_result": series_result,
        "gate5_evidence": bool(series_result and series_result.get("passed") is True),
        "last_result": last_result,
    }


def run_series(
    *,
    run_root: Path,
    metadata: dict[str, Any],
    max_hours: float,
    batch_observations: int,
    initial_backoff_seconds: float,
    max_backoff_seconds: float,
    between_batches_seconds: float,
    preflight_timeout: int,
    observation_timeout: int,
    max_model_calls: int,
    preflight_fn: Callable[..., tuple[int, dict[str, Any]]] = _invoke_preflight,
    batch_fn: Callable[..., tuple[int, dict[str, Any]]] = _invoke_phase_batch,
    sleep_fn: Callable[[float], None] = time.sleep,
    monotonic_fn: Callable[[], float] = time.monotonic,
) -> tuple[int, dict[str, Any]]:
    run_root = run_root.resolve()
    model = str(metadata["model"])
    provider = str(metadata["provider"]) if metadata.get("provider") else None
    thinking = str(metadata["thinking"]) if metadata.get("thinking") else None
    runtime = _path_from_metadata(run_root, metadata, "runtime")

    env = os.environ.copy()
    env["PI_EVAL_MODEL"] = model
    if provider:
        env["PI_EVAL_PROVIDER"] = provider
    else:
        env.pop("PI_EVAL_PROVIDER", None)
    if thinking:
        env["PI_EVAL_THINKING"] = thinking
    else:
        env.pop("PI_EVAL_THINKING", None)

    started_at = _utc_now()
    deadline = monotonic_fn() + max_hours * 3600
    model_calls = 0
    preflight_attempts = 0
    batch_attempts = 0
    backoff = initial_backoff_seconds
    needs_preflight = True
    last_result: dict[str, Any] | None = None
    series_result: dict[str, Any] | None = None
    status_path = run_root / "series-status.json"

    def finish(
        exit_code: int,
        status: str,
        reason: str,
        phase_id: str | None = None,
    ) -> tuple[int, dict[str, Any]]:
        payload = _status_payload(
            run_root=run_root,
            metadata=metadata,
            started_at=started_at,
            status=status,
            stop_reason=reason,
            current_phase=phase_id,
            model_calls_upper_bound=model_calls,
            max_model_calls=max_model_calls,
            preflight_attempts=preflight_attempts,
            batch_attempts=batch_attempts,
            last_result=last_result,
            series_result=series_result,
        )
        _write_json(status_path, payload)
        print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
        return exit_code, payload

    while True:
        states = _all_phase_states(run_root, metadata)
        phase, terminal = _current_phase(states)
        if terminal == "aa_noise_gate_failed":
            return finish(5, "blocked", terminal, "aa")
        if terminal == "ab_round_1_failed":
            return finish(5, "blocked", terminal, "ab-round-1")
        if terminal == "ab_round_2_failed":
            return finish(5, "blocked", terminal, "ab-round-2")
        if terminal == "all_phases_passed":
            series_result = _verify_series(run_root, metadata)
            if series_result.get("passed") is True:
                return finish(0, "complete", "gate5_series_passed")
            return finish(5, "blocked", "series_verification_failed")

        assert phase is not None
        if monotonic_fn() >= deadline:
            return finish(INCOMPLETE_EXIT, "paused", "wall_clock_deadline", str(phase["id"]))
        if model_calls >= max_model_calls:
            return finish(INCOMPLETE_EXIT, "paused", "model_call_budget", str(phase["id"]))

        if needs_preflight:
            if model_calls + 1 > max_model_calls:
                return finish(
                    INCOMPLETE_EXIT,
                    "paused",
                    "model_call_budget",
                    str(phase["id"]),
                )
            preflight_attempts += 1
            print(
                f"Preflight {preflight_attempts}: {model} "
                f"({thinking or 'provider default'})",
                file=sys.stderr,
                flush=True,
            )
            _code, preflight = preflight_fn(
                runtime=runtime,
                model=model,
                provider=provider,
                thinking=thinking,
                timeout=preflight_timeout,
                env=env,
            )
            model_calls += 1
            last_result = preflight
            if preflight.get("ready") is not True:
                if not _quota_or_rate_limited(preflight):
                    return finish(
                        2,
                        "error",
                        "preflight_non_retryable",
                        str(phase["id"]),
                    )
                remaining_seconds = max(0.0, deadline - monotonic_fn())
                delay = min(backoff, remaining_seconds)
                if delay <= 0:
                    return finish(
                        INCOMPLETE_EXIT,
                        "paused",
                        "wall_clock_deadline",
                        str(phase["id"]),
                    )
                _write_json(
                    status_path,
                    _status_payload(
                        run_root=run_root,
                        metadata=metadata,
                        started_at=started_at,
                        status="backing_off",
                        stop_reason="quota_or_rate_limit",
                        current_phase=str(phase["id"]),
                        model_calls_upper_bound=model_calls,
                        max_model_calls=max_model_calls,
                        preflight_attempts=preflight_attempts,
                        batch_attempts=batch_attempts,
                        last_result=last_result,
                        series_result=series_result,
                    ),
                )
                print(
                    f"Preflight hit quota/rate limit; backing off {int(delay)}s",
                    file=sys.stderr,
                    flush=True,
                )
                sleep_fn(delay)
                backoff = min(
                    max_backoff_seconds,
                    max(initial_backoff_seconds, backoff * 2),
                )
                continue
            needs_preflight = False
            backoff = initial_backoff_seconds

        states = _all_phase_states(run_root, metadata)
        phase, terminal = _current_phase(states)
        if terminal is not None:
            continue
        assert phase is not None
        budget_observations = (max_model_calls - model_calls) // 2
        batch = min(
            batch_observations,
            int(phase["remaining_observations"]),
            budget_observations,
        )
        if batch < 1:
            return finish(
                INCOMPLETE_EXIT,
                "paused",
                "model_call_budget",
                str(phase["id"]),
            )

        before = int(phase["completed_observations"])
        batch_attempts += 1
        print(
            f"Phase {phase['id']}; batch {batch_attempts}: up to {batch} "
            f"observations; checkpoint {before}/{phase['total_observations']}",
            file=sys.stderr,
            flush=True,
        )
        returncode, result = batch_fn(
            run_root=run_root,
            metadata=metadata,
            phase=phase,
            observations=batch,
            observation_timeout=observation_timeout,
            env=env,
        )
        last_result = result
        after = _phase_state(
            run_root,
            metadata,
            next(
                item
                for item in metadata["phase_order"]
                if item["id"] == phase["id"]
            ),
        )
        added = max(0, int(after["completed_observations"]) - before)
        failed_in_flight = bool(
            (_runner_error(result) or returncode not in (0, 5, INCOMPLETE_EXIT))
            and added < batch
        )
        model_calls += 2 * added + (2 if failed_in_flight else 0)
        model_calls = min(model_calls, max_model_calls)

        _write_json(
            status_path,
            _status_payload(
                run_root=run_root,
                metadata=metadata,
                started_at=started_at,
                status="running",
                stop_reason=None,
                current_phase=str(phase["id"]),
                model_calls_upper_bound=model_calls,
                max_model_calls=max_model_calls,
                preflight_attempts=preflight_attempts,
                batch_attempts=batch_attempts,
                last_result=last_result,
                series_result=series_result,
            ),
        )

        if _quota_or_rate_limited(result):
            needs_preflight = True
            remaining_seconds = max(0.0, deadline - monotonic_fn())
            delay = min(backoff, remaining_seconds)
            if delay <= 0:
                return finish(
                    INCOMPLETE_EXIT,
                    "paused",
                    "wall_clock_deadline",
                    str(phase["id"]),
                )
            print(
                f"Batch hit quota/rate limit after {added} observations; "
                f"backing off {int(delay)}s",
                file=sys.stderr,
                flush=True,
            )
            sleep_fn(delay)
            backoff = min(
                max_backoff_seconds,
                max(initial_backoff_seconds, backoff * 2),
            )
            continue

        if returncode in (0, 5):
            # The phase report now decides whether the next phase is allowed.
            backoff = initial_backoff_seconds
            continue
        if returncode == INCOMPLETE_EXIT and result.get("status") == "paused":
            delay = min(
                between_batches_seconds,
                max(0.0, deadline - monotonic_fn()),
            )
            if delay > 0:
                sleep_fn(delay)
            backoff = initial_backoff_seconds
            continue
        return finish(
            2,
            "error",
            "phase_non_retryable",
            str(phase["id"]),
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run-root",
        type=Path,
        default=ROOT / "scratchpad" / "gate5-series-v3-overnight",
        help="new or resumable run directory",
    )
    parser.add_argument("--baseline-ref", default=DEFAULT_BASELINE_REF)
    parser.add_argument("--model", default=os.environ.get("PI_EVAL_MODEL"))
    parser.add_argument("--provider", default=os.environ.get("PI_EVAL_PROVIDER"))
    parser.add_argument("--thinking", default=os.environ.get("PI_EVAL_THINKING"))
    parser.add_argument("--repetitions", type=int, default=5)
    parser.add_argument("--max-hours", type=float, default=8.0)
    parser.add_argument("--batch-observations", type=int, default=8)
    parser.add_argument("--initial-backoff-seconds", type=float, default=300.0)
    parser.add_argument("--max-backoff-seconds", type=float, default=1800.0)
    parser.add_argument("--between-batches-seconds", type=float, default=30.0)
    parser.add_argument("--preflight-timeout", type=int, default=120)
    parser.add_argument("--observation-timeout", type=int, default=900)
    parser.add_argument(
        "--confirm-max-model-calls",
        type=int,
        required=True,
        help=(
            "hard upper bound for this invocation; a full three-phase series "
            "needs at least 481 calls including one preflight"
        ),
    )
    args = parser.parse_args(argv)

    if args.repetitions < 1:
        parser.error("--repetitions must be positive")
    if args.max_hours <= 0:
        parser.error("--max-hours must be positive")
    if args.batch_observations < 1:
        parser.error("--batch-observations must be positive")
    if args.initial_backoff_seconds <= 0 or args.max_backoff_seconds <= 0:
        parser.error("backoff values must be positive")
    if args.max_backoff_seconds < args.initial_backoff_seconds:
        parser.error("--max-backoff-seconds must be >= initial backoff")
    if args.between_batches_seconds < 0:
        parser.error("--between-batches-seconds cannot be negative")
    if args.preflight_timeout < 1 or args.observation_timeout < 1:
        parser.error("timeouts must be positive")
    if args.confirm_max_model_calls < 1:
        parser.error("--confirm-max-model-calls must be positive")

    run_root = args.run_root.expanduser().resolve()
    try:
        metadata, model, provider, thinking = _load_or_prepare(
            run_root=run_root,
            baseline_ref=args.baseline_ref,
            model=(str(args.model).strip() if args.model else None),
            provider=(str(args.provider).strip() if args.provider else None),
            thinking=(str(args.thinking).strip() if args.thinking else None),
            repetitions=args.repetitions,
        )
        print(
            f"Gate 5 fixed-jury series: suite v{metadata['suite_version']}, "
            f"{metadata['case_count']} cases, {metadata['repetitions']} repetitions",
            file=sys.stderr,
        )
        print(
            "Phases: A/A -> A/B round 1 -> A/B round 2; "
            "each later phase is gated by the previous report",
            file=sys.stderr,
        )
        print(
            f"Candidate skills: {', '.join(metadata['skill_names']['candidate'])}",
            file=sys.stderr,
        )
        print(
            f"Baseline skills: {', '.join(metadata['skill_names']['baseline'])}",
            file=sys.stderr,
        )
        print(f"Model: {model}; thinking: {thinking or 'provider default'}", file=sys.stderr)
        print(f"Run root: {run_root}", file=sys.stderr)
        print(
            f"Bound: {args.max_hours:g} hours / "
            f"{args.confirm_max_model_calls} model calls this invocation",
            file=sys.stderr,
            flush=True,
        )
        exit_code, _payload = run_series(
            run_root=run_root,
            metadata=metadata,
            max_hours=args.max_hours,
            batch_observations=args.batch_observations,
            initial_backoff_seconds=args.initial_backoff_seconds,
            max_backoff_seconds=args.max_backoff_seconds,
            between_batches_seconds=args.between_batches_seconds,
            preflight_timeout=args.preflight_timeout,
            observation_timeout=args.observation_timeout,
            max_model_calls=args.confirm_max_model_calls,
        )
        return exit_code
    except KeyboardInterrupt:
        metadata_path = run_root / "series-metadata.json"
        if metadata_path.is_file():
            metadata = _load_json(metadata_path)
            payload = _status_payload(
                run_root=run_root,
                metadata=metadata,
                started_at=_utc_now(),
                status="paused",
                stop_reason="operator_interrupt",
                current_phase=None,
                model_calls_upper_bound=0,
                max_model_calls=args.confirm_max_model_calls,
                preflight_attempts=0,
                batch_attempts=0,
                last_result=None,
                series_result=None,
            )
            _write_json(run_root / "series-status.json", payload)
            print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
        return 130
    except Exception as exc:  # noqa: BLE001 - emit one actionable local failure
        result = {
            "runner_error": {
                "code": "gate5_series_setup_or_runtime_error",
                "message": str(exc)[:1000],
                "run_root": str(run_root),
                "next_action": (
                    "Inspect the frozen run metadata/status. Do not delete completed "
                    "phase checkpoints or start A/B manually."
                ),
            }
        }
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
