#!/usr/bin/env -S uv run --script
#
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Build or resume the retained PROCESIO Control Tower project through local Pi.

The coordinator runs six gated phases in fresh contexts with one exact model. It
never retries a phase automatically after an ambiguous exit because the phase may
already have committed PROCESIO state. Every successful phase must write a stable
checkpoint report before the next phase can begin.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PROJECT_DIR = ROOT / "examples" / "procesio" / "control-tower"
CONTRACT = PROJECT_DIR / "control-tower.field-contract.md"
MANIFEST = PROJECT_DIR / "control-tower.project.json"
SEEDS = PROJECT_DIR / "seed-evidence.json"
OPENAPI = PROJECT_DIR / "github-public-pulse.openapi.json"
SKILL = ROOT / "skills" / "procesio-cli"
DEFAULT_RUN_ROOT = ROOT / "scratchpad" / "procesio-control-tower-v1"
DEFAULT_MODEL = "zai/glm-5.3"
DEFAULT_THINKING = "high"
CONFIRMATION = "BUILD_PROCESIO_CONTROL_TOWER_V1"
PROJECT_ID = "procesio-control-tower-v1"


@dataclass(frozen=True)
class Phase:
    phase_id: str
    title: str
    mutation_scope: str
    allow_gap: bool = False


PHASES: tuple[Phase, ...] = (
    Phase(
        "01-discovery-and-blueprint",
        "Discovery, collision inventory, action resolution, and immutable blueprint",
        "read-only; local token generation only",
    ),
    Phase(
        "02-ledger-and-ingest",
        "Evidence data model, native ledger, and idempotent ingest process",
        "one data model, one data store, one process, bounded test rows/runs",
    ),
    Phase(
        "03-github-connector-and-pulse",
        "Read-only GitHub connector and repository-pulse process",
        "one connector/custom action, optional non-secret credential, one process",
        allow_gap=True,
    ),
    Phase(
        "04-founder-brief-and-schedule",
        "Founder PDF, weekly orchestrator, real seeds, and disabled-first schedule",
        "one document, two processes, one schedule, bounded seed/run/file operations",
    ),
    Phase(
        "05-mission-control-and-webhook-drill",
        "Published Mission Control form and temporary webhook lifecycle",
        "one retained form; one temporary webhook that must be detached and deleted",
    ),
    Phase(
        "06-export-audit-and-acceptance",
        "Final inventory, export, CSV proof, deployment manifest, and acceptance",
        "no new feature resources; export/download and direct verification only",
    ),
)

PASS_STATUSES = {"passed", "passed_with_gap"}
ALL_STATUSES = PASS_STATUSES | {"blocked", "unknown", "failed"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not readable JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must contain one JSON object")
    return value


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _emit(value: dict[str, Any]) -> None:
    print(json.dumps(value, ensure_ascii=False, separators=(",", ":")))


def _required_files() -> tuple[Path, ...]:
    return (CONTRACT, MANIFEST, SEEDS, OPENAPI, SKILL / "SKILL.md")


def _model_inventory(pi: str, model: str) -> tuple[bool, list[str], str]:
    """Resolve one exact provider/model from `pi --list-models` without a model call."""
    provider, separator, model_name = model.partition("/")
    if not separator or not provider or not model_name:
        return False, [], "model must be an exact provider/model identifier"
    try:
        proc = subprocess.run(
            [pi, "--list-models"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, [], f"could not list Pi models: {exc}"
    output = "\n".join(part for part in (proc.stdout, proc.stderr) if part)
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    provider_cf = provider.casefold()
    model_cf = model_name.casefold()
    exact = [
        line for line in lines
        if provider_cf in line.casefold() and model_cf in line.casefold()
    ]
    related = [line for line in lines if model_cf in line.casefold()][:12]
    if proc.returncode != 0:
        return False, related, f"pi --list-models exited {proc.returncode}"
    if not exact:
        return False, related, f"Pi did not list exact model {model!r}"
    return True, exact[:4], ""


def _phase_report_path(run_root: Path, phase: Phase) -> Path:
    return run_root / "phases" / f"{phase.phase_id}.json"


def _phase_log_path(run_root: Path, phase: Phase) -> Path:
    return run_root / "logs" / f"{phase.phase_id}.log"


def _validate_phase_report(path: Path, phase: Phase) -> dict[str, Any]:
    report = _load_object(path, f"phase report {path}")
    if report.get("schema_version") != 1:
        raise ValueError(f"{path}: schema_version must be 1")
    if report.get("project_id") != PROJECT_ID:
        raise ValueError(f"{path}: project_id must be {PROJECT_ID!r}")
    if report.get("phase") != phase.phase_id:
        raise ValueError(f"{path}: phase must be {phase.phase_id!r}")
    status = report.get("status")
    if status not in ALL_STATUSES:
        raise ValueError(f"{path}: unsupported status {status!r}")
    if status == "passed_with_gap" and not phase.allow_gap:
        raise ValueError(f"{path}: only phase 03 may pass with a documented gap")
    if status in PASS_STATUSES and report.get("next_phase_safe") is not True:
        raise ValueError(f"{path}: a passing phase requires next_phase_safe=true")
    unknowns = report.get("unknown_outcomes")
    if status in PASS_STATUSES and isinstance(unknowns, list) and unknowns:
        raise ValueError(f"{path}: a passing phase cannot contain unknown outcomes")
    return report


def _metadata_value(model: str, thinking: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "project_id": PROJECT_ID,
        "model": model,
        "thinking": thinking,
        "target": {
            "profile": "pure-awesomeness",
            "environment": "Internal-PROD",
            "workspace_id": "dc28053d-f701-4880-99c2-7d973899d135",
        },
        "inputs": {
            str(path.relative_to(ROOT)): _sha256(path)
            for path in (CONTRACT, MANIFEST, SEEDS, OPENAPI, SKILL / "SKILL.md")
        },
    }


def _init_or_validate_metadata(run_root: Path, model: str, thinking: str) -> dict[str, Any]:
    path = run_root / "coordinator-metadata.json"
    expected = _metadata_value(model, thinking)
    if path.exists():
        current = _load_object(path, "coordinator metadata")
        for key in ("schema_version", "project_id", "model", "thinking", "target", "inputs"):
            if current.get(key) != expected.get(key):
                raise ValueError(
                    f"cannot resume: coordinator metadata field {key!r} changed; "
                    "use a new --run-root rather than mixing project/model/contract versions"
                )
        return current
    value = {**expected, "created_at": _utc_now()}
    _atomic_json(path, value)
    return value


def _previous_reports(run_root: Path, current: Phase) -> list[dict[str, Any]]:
    reports: list[dict[str, Any]] = []
    for phase in PHASES:
        if phase.phase_id == current.phase_id:
            break
        path = _phase_report_path(run_root, phase)
        if path.exists():
            report = _validate_phase_report(path, phase)
            reports.append(
                {
                    "phase": report.get("phase"),
                    "status": report.get("status"),
                    "summary": report.get("summary"),
                    "report_path": str(path),
                }
            )
    return reports


def _prompt(run_root: Path, phase: Phase) -> str:
    report_path = _phase_report_path(run_root, phase)
    previous = _previous_reports(run_root, phase)
    return f"""You are executing one bounded phase of a real PROCESIO field project.

Project: {PROJECT_ID}
Phase: {phase.phase_id} — {phase.title}
Mutation scope for this phase: {phase.mutation_scope}
Exact phase report path: {report_path}

Read these committed files before acting:
- {CONTRACT}
- {MANIFEST}
- {SEEDS}
- {OPENAPI}
- {SKILL / 'SKILL.md'}

Previous passed phase summaries:
{json.dumps(previous, indent=2, ensure_ascii=False)}

Execute only the section of the field contract matching this phase. The operator has
approved exactly the mutations in this phase through the coordinator confirmation
phrase. Do not broaden the resource set. Carry profile pure-awesomeness, environment
Internal-PROD, and workspace ID dc28053d-f701-4880-99c2-7d973899d135 on every
PROCESIO call.

Use capability discovery and typed DTO/curated actions. Reconcile exact-title resources
before creating. Never blind-retry a timed-out write or run. Do not edit tracked repository
files. Save generated configs, packages, browser artifacts, exports, and evidence under
{run_root}.

At completion, atomically write the required phase-report JSON to {report_path}. The
report is the gate. Do not claim passed or next_phase_safe=true without direct proof and
without reconciling every mutation outcome. Then print a compact human-readable phase
summary.
"""


def _run_phase(
    *,
    pi: str,
    model: str,
    thinking: str,
    run_root: Path,
    phase: Phase,
    interactive_approval: bool,
    deadline: float,
) -> int:
    if time.monotonic() >= deadline:
        return 124
    command = [
        pi,
        "-p",
        "--no-session",
        "--no-skills",
    ]
    if not interactive_approval:
        command.append("--approve")
    command += [
        "--model", model,
        "--models", model,
        "--thinking", thinking,
        "--skill", str(SKILL),
        "--",
        _prompt(run_root, phase),
    ]
    log_path = _phase_log_path(run_root, phase)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    print(
        f"\n=== {phase.phase_id}: {phase.title} ===\n"
        f"Model: {model}; thinking: {thinking}\n"
        f"Report: {_phase_report_path(run_root, phase)}\n"
        f"Log: {log_path}",
        file=sys.stderr,
        flush=True,
    )
    with log_path.open("a", encoding="utf-8") as log:
        log.write(f"\n--- invocation {_utc_now()} ---\n")
        log.flush()
        try:
            proc = subprocess.Popen(
                command,
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=1,
            )
        except OSError as exc:
            log.write(f"launcher error: {exc}\n")
            print(f"launcher error: {exc}", file=sys.stderr)
            return 127
        assert proc.stdout is not None
        try:
            for line in proc.stdout:
                sys.stdout.write(line)
                sys.stdout.flush()
                log.write(line)
                log.flush()
                if time.monotonic() >= deadline and proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=20)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                    log.write("coordinator wall-clock deadline reached\n")
                    return 124
        except KeyboardInterrupt:
            if proc.poll() is None:
                proc.terminate()
            try:
                proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                proc.kill()
            return 130
        return proc.wait()


def _status(
    run_root: Path,
    *,
    state: str,
    reason: str,
    current_phase: str | None,
    model: str,
    thinking: str,
    started_at: str,
) -> dict[str, Any]:
    phases: list[dict[str, Any]] = []
    for phase in PHASES:
        path = _phase_report_path(run_root, phase)
        if path.exists():
            try:
                report = _validate_phase_report(path, phase)
                phase_status = report.get("status")
                summary = report.get("summary")
            except ValueError as exc:
                phase_status = "invalid_report"
                summary = str(exc)
        else:
            phase_status = "pending"
            summary = None
        phases.append(
            {
                "id": phase.phase_id,
                "status": phase_status,
                "summary": summary,
                "report_path": str(path),
            }
        )
    value = {
        "schema_version": 1,
        "kind": "procesio-control-tower-coordinator-status",
        "project_id": PROJECT_ID,
        "state": state,
        "reason": reason,
        "current_phase": current_phase,
        "model": model,
        "thinking": thinking,
        "run_root": str(run_root),
        "started_at": started_at,
        "updated_at": _utc_now(),
        "phases": phases,
        "automatic_phase_retries": 0,
        "final_report": str(run_root / "final-report.json"),
        "deployment_manifest": str(run_root / "deployment.json"),
    }
    _atomic_json(run_root / "coordinator-status.json", value)
    return value


def _selected_phases(raw: list[str] | None) -> tuple[Phase, ...]:
    if not raw:
        return PHASES
    wanted = set(raw)
    known = {phase.phase_id for phase in PHASES}
    unknown = sorted(wanted - known)
    if unknown:
        raise ValueError("unknown --phase values: " + ", ".join(unknown))
    return tuple(phase for phase in PHASES if phase.phase_id in wanted)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=os.environ.get("PI_CONTROL_TOWER_MODEL", DEFAULT_MODEL))
    parser.add_argument("--thinking", default=os.environ.get("PI_CONTROL_TOWER_THINKING", DEFAULT_THINKING))
    parser.add_argument("--run-root", type=Path, default=DEFAULT_RUN_ROOT)
    parser.add_argument("--max-hours", type=float, default=12.0)
    parser.add_argument("--confirm", help=f"required exact value: {CONFIRMATION}")
    parser.add_argument("--phase", action="append", help="run only one named phase; repeatable")
    parser.add_argument("--interactive-approval", action="store_true", help="omit Pi --approve")
    parser.add_argument("--dry-run", action="store_true", help="print the plan; no Pi or PROCESIO calls")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    started_at = _utc_now()
    model = str(args.model).strip()
    thinking = str(args.thinking).strip()
    run_root = args.run_root.expanduser().resolve()

    try:
        phases = _selected_phases(args.phase)
        missing = [str(path) for path in _required_files() if not path.exists()]
        if missing:
            raise ValueError("required project files are missing: " + ", ".join(missing))
        manifest = _load_object(MANIFEST, "project manifest")
        if manifest.get("project_id") != PROJECT_ID:
            raise ValueError("project manifest identity does not match the coordinator")
        if args.max_hours <= 0:
            raise ValueError("--max-hours must be positive")
    except ValueError as exc:
        _emit({"error": {"code": "invalid_configuration", "message": str(exc), "details": {}}})
        return 2

    if args.dry_run:
        _emit(
            {
                "schema_version": 1,
                "dry_run": True,
                "project_id": PROJECT_ID,
                "model": model,
                "thinking": thinking,
                "run_root": str(run_root),
                "target": manifest["target"],
                "phases": [
                    {
                        "id": phase.phase_id,
                        "title": phase.title,
                        "mutation_scope": phase.mutation_scope,
                    }
                    for phase in phases
                ],
                "automatic_phase_retries": 0,
                "confirmation_required": CONFIRMATION,
                "platform_calls": 0,
                "model_calls": 0,
            }
        )
        return 0

    if args.confirm != CONFIRMATION:
        _emit(
            {
                "error": {
                    "code": "confirmation_required",
                    "message": f"Pass --confirm {CONFIRMATION} to authorize the bounded project contract.",
                    "details": {"project_id": PROJECT_ID},
                }
            }
        )
        return 2

    pi = os.environ.get("PI_BIN", "pi")
    if not shutil.which(pi) and not Path(pi).is_file():
        _emit({"error": {"code": "pi_not_found", "message": f"Pi executable not found: {pi!r}", "details": {}}})
        return 2

    available, model_lines, model_error = _model_inventory(pi, model)
    if not available:
        _emit(
            {
                "error": {
                    "code": "model_not_available",
                    "message": model_error,
                    "details": {
                        "requested_model": model,
                        "related_model_lines": model_lines,
                        "silent_fallback": False,
                    },
                }
            }
        )
        return 2

    try:
        run_root.mkdir(parents=True, exist_ok=True)
        _init_or_validate_metadata(run_root, model, thinking)
    except (OSError, ValueError) as exc:
        _emit({"error": {"code": "resume_contract_mismatch", "message": str(exc), "details": {"run_root": str(run_root)}}})
        return 2

    deadline = time.monotonic() + args.max_hours * 3600
    print(
        "PROCESIO Control Tower coordinator\n"
        f"Model: {model}; thinking: {thinking}\n"
        f"Target: pure-awesomeness / Internal-PROD / dc28053d-f701-4880-99c2-7d973899d135\n"
        f"Run root: {run_root}\n"
        f"Model inventory match: {model_lines[0] if model_lines else model}",
        file=sys.stderr,
        flush=True,
    )

    for phase in phases:
        report_path = _phase_report_path(run_root, phase)
        if report_path.exists():
            try:
                report = _validate_phase_report(report_path, phase)
            except ValueError as exc:
                value = _status(
                    run_root,
                    state="error",
                    reason=f"invalid existing phase report: {exc}",
                    current_phase=phase.phase_id,
                    model=model,
                    thinking=thinking,
                    started_at=started_at,
                )
                _emit(value)
                return 2
            if report["status"] in PASS_STATUSES and report["next_phase_safe"] is True:
                print(f"Skipping passed phase {phase.phase_id}: {report.get('summary')}", file=sys.stderr)
                continue
            value = _status(
                run_root,
                state="blocked",
                reason=f"existing phase report is {report['status']}; inspect it before resuming",
                current_phase=phase.phase_id,
                model=model,
                thinking=thinking,
                started_at=started_at,
            )
            _emit(value)
            return 1

        if time.monotonic() >= deadline:
            value = _status(
                run_root,
                state="paused",
                reason="wall-clock limit reached before the next phase",
                current_phase=phase.phase_id,
                model=model,
                thinking=thinking,
                started_at=started_at,
            )
            _emit(value)
            return 75

        code = _run_phase(
            pi=pi,
            model=model,
            thinking=thinking,
            run_root=run_root,
            phase=phase,
            interactive_approval=args.interactive_approval,
            deadline=deadline,
        )
        if code != 0:
            state = "paused" if code in (124, 130) else "unknown"
            reason = (
                "phase stopped by wall-clock limit or operator; inspect platform state before resuming"
                if code in (124, 130)
                else "Pi exited without a verified passing phase report; the platform outcome may be partial or unknown"
            )
            value = _status(
                run_root,
                state=state,
                reason=reason,
                current_phase=phase.phase_id,
                model=model,
                thinking=thinking,
                started_at=started_at,
            )
            value["child_exit_code"] = code
            _atomic_json(run_root / "coordinator-status.json", value)
            _emit(value)
            return 75 if code in (124, 130) else 1

        if not report_path.exists():
            value = _status(
                run_root,
                state="unknown",
                reason="Pi exited successfully but did not write the required phase report; reconcile before rerunning",
                current_phase=phase.phase_id,
                model=model,
                thinking=thinking,
                started_at=started_at,
            )
            _emit(value)
            return 1

        try:
            report = _validate_phase_report(report_path, phase)
        except ValueError as exc:
            value = _status(
                run_root,
                state="error",
                reason=f"new phase report is invalid: {exc}",
                current_phase=phase.phase_id,
                model=model,
                thinking=thinking,
                started_at=started_at,
            )
            _emit(value)
            return 2
        if report["status"] not in PASS_STATUSES or report["next_phase_safe"] is not True:
            value = _status(
                run_root,
                state="blocked",
                reason=f"phase ended with status {report['status']!r}; later phases were not started",
                current_phase=phase.phase_id,
                model=model,
                thinking=thinking,
                started_at=started_at,
            )
            _emit(value)
            return 1

    final_report = run_root / "final-report.json"
    deployment = run_root / "deployment.json"
    state = "complete" if final_report.exists() and deployment.exists() else "complete_with_missing_artifact"
    reason = (
        "all selected phases passed"
        if state == "complete"
        else "all selected phases passed, but final report/deployment artifacts are not both present"
    )
    value = _status(
        run_root,
        state=state,
        reason=reason,
        current_phase=None,
        model=model,
        thinking=thinking,
        started_at=started_at,
    )
    value["final_report_exists"] = final_report.exists()
    value["deployment_manifest_exists"] = deployment.exists()
    _atomic_json(run_root / "coordinator-status.json", value)
    _emit(value)
    return 0 if state == "complete" or phases != PHASES else 1


if __name__ == "__main__":
    raise SystemExit(main())
