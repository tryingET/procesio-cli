#!/usr/bin/env -S uv run --script
#
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Repair Control Tower Phase 05, promote it only on proof, then finish Phase 06.

The original Phase 05 report exposed two real platform-integration gaps. This
coordinator does not waive them. It runs three fixed-check remediation stages in
fresh Pi contexts, archives the original report, promotes Phase 05 to ``passed``
only after every required check succeeds, and then invokes the original Phase 06.
There are no automatic stage retries after an ambiguous exit.
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
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PROJECT_DIR = ROOT / "examples" / "procesio" / "control-tower"
ORIGINAL_CONTRACT = PROJECT_DIR / "control-tower.field-contract.md"
REMEDIATION_CONTRACT = PROJECT_DIR / "phase05-remediation.field-contract.md"
MANIFEST = PROJECT_DIR / "control-tower.project.json"
SKILL = ROOT / "skills" / "procesio-cli"
CONTROL_TOWER = ROOT / "scripts" / "run-procesio-control-tower.py"
DEFAULT_RUN_ROOT = ROOT / "scratchpad" / "procesio-control-tower-v1"
DEFAULT_MODEL = "zai/glm-5.3"
DEFAULT_THINKING = "high"
CONFIRMATION = "REMEDIATE_AND_FINISH_PROCESIO_CONTROL_TOWER_V1"
ORIGINAL_CONFIRMATION = "BUILD_PROCESIO_CONTROL_TOWER_V1"
PROJECT_ID = "procesio-control-tower-v1"
REMEDIATION_ID = "control-tower-phase05-remediation-v1"
PHASE05_ID = "05-mission-control-and-webhook-drill"
PHASE06_ID = "06-export-audit-and-acceptance"
TOTAL_BUDGET = {
    "form_submissions": 1,
    "webhook_launches": 1,
    "process_instances": 5,
}


@dataclass(frozen=True)
class Stage:
    stage_id: str
    title: str
    mutation_scope: str
    required_checks: tuple[str, ...]
    budget_limits: dict[str, int]


STAGES: tuple[Stage, ...] = (
    Stage(
        "05r-1-native-form-result",
        "Native synchronous form-result contract",
        "edit Ingest Evidence and Mission Control only; one browser submission",
        (
            "before_snapshots_and_digests_saved",
            "ingest_public_inputs_outputs_preserved",
            "custom_response_has_native_variable_envelope",
            "direct_structured_response_preserved",
            "form_output_map_matches_live_variable_ids",
            "ingest_backend_and_designer_valid",
            "form_published_and_valid",
            "one_real_form_submission",
            "native_form_result_rendered_without_manual_writer",
            "form_decision_resume_checkpoint_visible",
            "form_next_action_visible",
            "form_ledger_row_unique",
            "access_token_not_persisted_or_exposed",
            "no_unknown_outcomes",
        ),
        {"form_submissions": 1, "webhook_launches": 0, "process_instances": 2},
    ),
    Stage(
        "05r-2-whole-body-webhook",
        "Whole-body webhook adapter and complete cleanup",
        "one temporary webhook and at most one temporary adapter process; one launch",
        (
            "temporary_titles_absent_before_create",
            "webhook_model_and_attributes_resolved",
            "whole_body_model_binding_used",
            "adapter_calls_ingest_with_plain_variables",
            "temporary_path_backend_and_designer_valid",
            "one_webhook_launch_only",
            "webhook_instance_reconciled",
            "ingest_child_finished",
            "webhook_decision_investigate_gate",
            "webhook_ledger_row_unique",
            "webhook_detached_and_deleted",
            "temporary_adapter_deleted_or_not_used",
            "temporary_webhook_model_removed_or_unreferenced",
            "retained_ingest_contract_restored_and_valid",
            "zero_retained_anonymous_webhooks",
            "no_unknown_outcomes",
        ),
        {"form_submissions": 0, "webhook_launches": 1, "process_instances": 3},
    ),
    Stage(
        "05r-3-reconcile-and-promote",
        "Final reconciliation and promotion readiness",
        "read-only platform verification; local report promotion only",
        (
            "form_native_result_proof_present",
            "webhook_end_to_end_proof_present",
            "form_and_ingest_current_state_valid",
            "sibling_control_tower_resources_valid",
            "schedule_unchanged_and_enabled",
            "two_remediation_rows_unique_and_correct",
            "zero_temporary_webhooks",
            "zero_temporary_adapters",
            "zero_temporary_webhook_models",
            "no_secret_exposure",
            "execution_budget_exception_recorded",
            "original_phase05_gaps_resolved",
            "promotion_to_phase05_passed_is_safe",
            "no_unknown_outcomes",
        ),
        {"form_submissions": 0, "webhook_launches": 0, "process_instances": 0},
    ),
)

STAGE_STATUSES = {"passed", "blocked", "unknown", "failed"}


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


def _atomic_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_bytes(source.read_bytes())
    temporary.replace(destination)


def _emit(value: dict[str, Any]) -> None:
    print(json.dumps(value, ensure_ascii=False, separators=(",", ":")))


def _required_files() -> tuple[Path, ...]:
    return (
        ORIGINAL_CONTRACT,
        REMEDIATION_CONTRACT,
        MANIFEST,
        SKILL / "SKILL.md",
        CONTROL_TOWER,
    )


def _model_inventory(pi: str, model: str) -> tuple[bool, list[str], str]:
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
        line
        for line in lines
        if provider_cf in line.casefold() and model_cf in line.casefold()
    ]
    related = [line for line in lines if model_cf in line.casefold()][:12]
    if proc.returncode != 0:
        return False, related, f"pi --list-models exited {proc.returncode}"
    if not exact:
        return False, related, f"Pi did not list exact model {model!r}"
    return True, exact[:4], ""


def _phase05_path(run_root: Path) -> Path:
    return run_root / "phases" / f"{PHASE05_ID}.json"


def _phase06_path(run_root: Path) -> Path:
    return run_root / "phases" / f"{PHASE06_ID}.json"


def _remediation_root(run_root: Path) -> Path:
    return run_root / "remediation" / "phase05"


def _stage_report_path(run_root: Path, stage: Stage) -> Path:
    return _remediation_root(run_root) / "stages" / f"{stage.stage_id}.json"


def _stage_log_path(run_root: Path, stage: Stage) -> Path:
    return _remediation_root(run_root) / "logs" / f"{stage.stage_id}.log"


def _phase05_state(run_root: Path) -> tuple[str, dict[str, Any]]:
    path = _phase05_path(run_root)
    report = _load_object(path, "original Phase 05 report")
    if report.get("schema_version") != 1:
        raise ValueError("Phase 05 report schema_version must be 1")
    if report.get("project_id") != PROJECT_ID or report.get("phase") != PHASE05_ID:
        raise ValueError("Phase 05 report identity does not match this project")
    status = report.get("status")
    remediation = report.get("remediation")
    if (
        status == "passed"
        and isinstance(remediation, dict)
        and remediation.get("remediation_id") == REMEDIATION_ID
    ):
        return "promoted", report
    if status != "passed_with_gap":
        raise ValueError(
            "expected the unresolved Phase 05 report to have status passed_with_gap; "
            f"observed {status!r}"
        )
    unknowns = report.get("unknown_outcomes")
    if isinstance(unknowns, list) and unknowns:
        raise ValueError("Phase 05 contains unknown outcomes; reconcile them before remediation")
    gaps_text = json.dumps(report.get("gaps") or [], ensure_ascii=False).casefold()
    for marker in ("form-sync-result-rendering", "webhook-field-mapping"):
        if marker not in gaps_text:
            raise ValueError(f"Phase 05 report does not contain expected gap {marker!r}")
    return "unresolved", report


def _check_map(report: dict[str, Any], path: Path) -> dict[str, dict[str, Any]]:
    checks = report.get("checks")
    if not isinstance(checks, list):
        raise ValueError(f"{path}: checks must be a list")
    out: dict[str, dict[str, Any]] = {}
    for item in checks:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            raise ValueError(f"{path}: every check must be an object with a string id")
        cid = item["id"]
        if cid in out:
            raise ValueError(f"{path}: duplicate check id {cid!r}")
        out[cid] = item
    return out


def _budget_usage(report: dict[str, Any], path: Path) -> dict[str, int]:
    raw = report.get("budget_usage")
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: budget_usage must be an object")
    usage: dict[str, int] = {}
    for key in TOTAL_BUDGET:
        value = raw.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{path}: budget_usage.{key} must be a non-negative integer")
        usage[key] = value
    return usage


def _validate_stage_report(path: Path, stage: Stage) -> dict[str, Any]:
    report = _load_object(path, f"stage report {path}")
    if report.get("schema_version") != 1:
        raise ValueError(f"{path}: schema_version must be 1")
    if report.get("project_id") != PROJECT_ID:
        raise ValueError(f"{path}: project_id must be {PROJECT_ID!r}")
    if report.get("remediation_id") != REMEDIATION_ID:
        raise ValueError(f"{path}: remediation_id must be {REMEDIATION_ID!r}")
    if report.get("stage") != stage.stage_id:
        raise ValueError(f"{path}: stage must be {stage.stage_id!r}")
    status = report.get("status")
    if status not in STAGE_STATUSES:
        raise ValueError(
            f"{path}: status must be passed, blocked, unknown, or failed; "
            "passed_with_gap is forbidden"
        )
    checks = _check_map(report, path)
    usage = _budget_usage(report, path)
    for key, limit in stage.budget_limits.items():
        if usage[key] > limit:
            raise ValueError(
                f"{path}: budget_usage.{key}={usage[key]} exceeds stage limit {limit}"
            )
    if status == "passed":
        expected = list(stage.required_checks)
        observed = list(checks)
        if observed != expected:
            raise ValueError(
                f"{path}: check ids/order must exactly match the fixed stage contract; "
                f"expected {expected!r}, observed {observed!r}"
            )
        failed = [cid for cid, item in checks.items() if item.get("passed") is not True]
        if failed:
            raise ValueError(f"{path}: passing stage has failed checks: {failed}")
        if report.get("next_stage_safe") is not True:
            raise ValueError(f"{path}: passing stage requires next_stage_safe=true")
        if report.get("gaps") not in ([], None):
            raise ValueError(f"{path}: passing remediation stage cannot retain gaps")
        if report.get("unknown_outcomes") not in ([], None):
            raise ValueError(f"{path}: passing remediation stage cannot retain unknown outcomes")
    return report


def _metadata_value(
    *,
    run_root: Path,
    model: str,
    thinking: str,
    original_phase05: dict[str, Any],
) -> dict[str, Any]:
    original_path = _phase05_path(run_root)
    return {
        "schema_version": 1,
        "project_id": PROJECT_ID,
        "remediation_id": REMEDIATION_ID,
        "model": model,
        "thinking": thinking,
        "target": {
            "profile": "pure-awesomeness",
            "environment": "Internal-PROD",
            "workspace_id": "dc28053d-f701-4880-99c2-7d973899d135",
        },
        "input_hashes": {
            str(path.relative_to(ROOT)): _sha256(path)
            for path in (
                ORIGINAL_CONTRACT,
                REMEDIATION_CONTRACT,
                MANIFEST,
                SKILL / "SKILL.md",
            )
        },
        "original_phase05_path": str(original_path),
        "original_phase05_sha256": _sha256(original_path),
        "original_gap_snapshot": original_phase05.get("gaps") or [],
        "evidence_keys": {
            "form": f"control-tower:phase05r:form:{uuid.uuid4()}",
            "webhook": f"control-tower:phase05r:webhook:{uuid.uuid4()}",
        },
        "total_budget": dict(TOTAL_BUDGET),
    }


def _init_or_validate_metadata(
    run_root: Path,
    *,
    model: str,
    thinking: str,
    original_phase05: dict[str, Any],
) -> dict[str, Any]:
    path = _remediation_root(run_root) / "metadata.json"
    if path.exists():
        current = _load_object(path, "remediation metadata")
        expected_hashes = {
            str(item.relative_to(ROOT)): _sha256(item)
            for item in (
                ORIGINAL_CONTRACT,
                REMEDIATION_CONTRACT,
                MANIFEST,
                SKILL / "SKILL.md",
            )
        }
        for key, value in {
            "schema_version": 1,
            "project_id": PROJECT_ID,
            "remediation_id": REMEDIATION_ID,
            "model": model,
            "thinking": thinking,
            "input_hashes": expected_hashes,
            "total_budget": TOTAL_BUDGET,
        }.items():
            if current.get(key) != value:
                raise ValueError(
                    f"cannot resume remediation: metadata field {key!r} changed; "
                    "use a new reviewed remediation version instead of mixing contracts"
                )
        keys = current.get("evidence_keys")
        if not isinstance(keys, dict) or not all(
            isinstance(keys.get(name), str) and keys[name]
            for name in ("form", "webhook")
        ):
            raise ValueError("remediation metadata has invalid stable evidence keys")
        return current
    value = {
        **_metadata_value(
            run_root=run_root,
            model=model,
            thinking=thinking,
            original_phase05=original_phase05,
        ),
        "created_at": _utc_now(),
    }
    _atomic_json(path, value)
    return value


def _previous_stage_summaries(run_root: Path, current: Stage) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for stage in STAGES:
        if stage.stage_id == current.stage_id:
            break
        path = _stage_report_path(run_root, stage)
        if path.exists():
            report = _validate_stage_report(path, stage)
            summaries.append(
                {
                    "stage": stage.stage_id,
                    "status": report.get("status"),
                    "summary": report.get("summary"),
                    "report_path": str(path),
                }
            )
    return summaries


def _stage_prompt(
    run_root: Path,
    stage: Stage,
    metadata: dict[str, Any],
) -> str:
    report_path = _stage_report_path(run_root, stage)
    previous = _previous_stage_summaries(run_root, stage)
    return f"""You are executing one bounded remediation stage of a real PROCESIO project.

Project: {PROJECT_ID}
Remediation: {REMEDIATION_ID}
Stage: {stage.stage_id} — {stage.title}
Mutation scope: {stage.mutation_scope}
Exact stage report path: {report_path}
Remediation root: {_remediation_root(run_root)}

Read these files before acting:
- {REMEDIATION_CONTRACT}
- {ORIGINAL_CONTRACT}
- {MANIFEST}
- {_phase05_path(run_root)}
- {run_root / 'phases' / '02-ledger-and-ingest.json'}
- {run_root / 'phases' / '04-founder-brief-and-schedule.json'}
- {SKILL / 'SKILL.md'}

Previous remediation stage summaries:
{json.dumps(previous, indent=2, ensure_ascii=False)}

Stable non-secret evidence keys generated before any platform mutation:
- form_evidence_key: {metadata['evidence_keys']['form']}
- webhook_evidence_key: {metadata['evidence_keys']['webhook']}
Never substitute a new key after an ambiguous outcome.

Fixed stage budget limits:
{json.dumps(stage.budget_limits, indent=2, sort_keys=True)}

The passing report must contain these check IDs exactly once, in this exact order,
and each must have passed=true:
{json.dumps(list(stage.required_checks), indent=2)}

Execute only the matching stage section in the remediation contract. Carry profile
pure-awesomeness, environment Internal-PROD, and workspace ID
dc28053d-f701-4880-99c2-7d973899d135 on every PROCESIO call. Use capability
discovery and typed/curated actions. Save all generated configs, snapshots, files,
masked screenshots, and evidence under the remediation root. Do not edit tracked
repository files.

The valid form token may be read only from {run_root / 'form-access-token.txt'}.
Never print it, persist it as a form default, put it in a report/log, or show it in
a screenshot.

There are no automatic retries. A timed-out or dropped write/run/submit/launch is an
unknown outcome: reconcile with the stable resource ID, evidence key, and time window,
then stop unless the result is proved. Do not issue another form submit or webhook
launch for the same claim.

Allowed stage statuses are passed, blocked, unknown, or failed. passed_with_gap is
forbidden. Write the exact report schema from the remediation contract atomically to
{report_path}. For passed, include every fixed check in exact order, empty gaps and
unknown_outcomes, truthful budget_usage, and next_stage_safe=true. Then print a compact
human-readable summary.
"""


def _run_stage(
    *,
    pi: str,
    model: str,
    thinking: str,
    run_root: Path,
    stage: Stage,
    metadata: dict[str, Any],
    interactive_approval: bool,
    deadline: float,
) -> int:
    if time.monotonic() >= deadline:
        return 124
    command = [pi, "-p", "--no-session", "--no-skills"]
    if not interactive_approval:
        command.append("--approve")
    command += [
        "--model", model,
        "--models", model,
        "--thinking", thinking,
        "--skill", str(SKILL),
        "--",
        _stage_prompt(run_root, stage, metadata),
    ]
    log_path = _stage_log_path(run_root, stage)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    print(
        f"\n=== {stage.stage_id}: {stage.title} ===\n"
        f"Model: {model}; thinking: {thinking}\n"
        f"Report: {_stage_report_path(run_root, stage)}\n"
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
                    log.write("remediation wall-clock deadline reached\n")
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


def _aggregate_budget(reports: list[dict[str, Any]]) -> dict[str, int]:
    total = {key: 0 for key in TOTAL_BUDGET}
    for index, report in enumerate(reports):
        path = Path(f"stage-{index + 1}")
        usage = _budget_usage(report, path)
        for key, value in usage.items():
            total[key] += value
    for key, limit in TOTAL_BUDGET.items():
        if total[key] > limit:
            raise ValueError(
                f"aggregate remediation budget {key}={total[key]} exceeds limit {limit}"
            )
    return total


def _promote_phase05(
    run_root: Path,
    *,
    metadata: dict[str, Any],
    reports: list[dict[str, Any]],
) -> dict[str, Any]:
    total_budget = _aggregate_budget(reports)
    phase05_path = _phase05_path(run_root)
    state, original = _phase05_state(run_root)
    if state == "promoted":
        return original
    current_hash = _sha256(phase05_path)
    if current_hash != metadata.get("original_phase05_sha256"):
        raise ValueError(
            "Phase 05 report changed since remediation metadata was created; "
            "refuse to overwrite unreviewed evidence"
        )

    archive_path = (
        run_root
        / "phases"
        / "archive"
        / f"{PHASE05_ID}.pre-remediation.json"
    )
    if archive_path.exists():
        if _sha256(archive_path) != current_hash:
            raise ValueError("existing Phase 05 archive does not match the original report")
    else:
        _atomic_copy(phase05_path, archive_path)

    resolved_gaps = original.get("gaps") or []
    remediation_checks: list[dict[str, Any]] = []
    remediation_resources: list[Any] = []
    remediation_executions: list[Any] = []
    for stage, report in zip(STAGES, reports):
        for check in report.get("checks") or []:
            remediation_checks.append(
                {
                    **check,
                    "id": f"{stage.stage_id}:{check['id']}",
                    "remediation_stage": stage.stage_id,
                }
            )
        remediation_resources.extend(report.get("resources") or [])
        remediation_executions.extend(report.get("executions") or [])

    summaries = [str(report.get("summary") or "").strip() for report in reports]
    promoted = dict(original)
    promoted.update(
        {
            "status": "passed",
            "summary": (
                "Phase 05 passed after separately approved targeted remediation: "
                "the published form now renders the real synchronous result natively, "
                "and the temporary webhook used the platform-native whole-body model "
                "adapter to produce the expected INVESTIGATE_GATE ledger row before "
                "complete detach/delete cleanup. No required Phase 05 gap remains."
            ),
            "gaps": [],
            "resolved_gaps": resolved_gaps,
            "unknown_outcomes": [],
            "next_phase_safe": True,
            "checks": (original.get("checks") or []) + remediation_checks,
            "resources": (original.get("resources") or []) + remediation_resources,
            "executions": (original.get("executions") or []) + remediation_executions,
            "remediation": {
                "remediation_id": REMEDIATION_ID,
                "approved_confirmation": CONFIRMATION,
                "contract": str(REMEDIATION_CONTRACT.relative_to(ROOT)),
                "original_report_archive": str(archive_path),
                "stage_reports": [
                    str(_stage_report_path(run_root, stage)) for stage in STAGES
                ],
                "stage_summaries": summaries,
                "resolved_gaps": resolved_gaps,
                "budget_exception": {
                    "reason": "repair two failed Phase 05 acceptance outcomes",
                    "original_build_instance_cap": 20,
                    "additional_usage": total_budget,
                    "maximum_additional_usage": TOTAL_BUDGET,
                    "silent_rewrite_of_prior_counts": False,
                },
                "design_amendment": (
                    "Webhook intake uses one temporary whole-body model adapter because "
                    "the platform does not fan out webhook fields into primitive inputs. "
                    "The adapter and webhook are deleted after proof."
                ),
                "promoted_at": _utc_now(),
            },
        }
    )
    _atomic_json(phase05_path, promoted)
    promotion = {
        "schema_version": 1,
        "project_id": PROJECT_ID,
        "remediation_id": REMEDIATION_ID,
        "status": "promoted",
        "phase": PHASE05_ID,
        "original_report_archive": str(archive_path),
        "promoted_report": str(phase05_path),
        "resolved_gaps": resolved_gaps,
        "budget_usage": total_budget,
        "promoted_at": promoted["remediation"]["promoted_at"],
    }
    _atomic_json(_remediation_root(run_root) / "promotion.json", promotion)
    return promoted


def _run_phase06(
    *,
    model: str,
    thinking: str,
    run_root: Path,
    interactive_approval: bool,
    max_hours: float,
) -> int:
    command = [
        os.environ.get("UV_BIN", "uv"),
        "run",
        "--script",
        str(CONTROL_TOWER),
        "--model",
        model,
        "--thinking",
        thinking,
        "--run-root",
        str(run_root),
        "--max-hours",
        str(max_hours),
        "--phase",
        PHASE06_ID,
        "--confirm",
        ORIGINAL_CONFIRMATION,
    ]
    if interactive_approval:
        command.append("--interactive-approval")
    log_path = _remediation_root(run_root) / "logs" / "06-export-audit-and-acceptance.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    print(
        "\n=== Continuing original Phase 06: export, audit, and acceptance ===\n"
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
            return 127
        assert proc.stdout is not None
        try:
            for line in proc.stdout:
                sys.stdout.write(line)
                sys.stdout.flush()
                log.write(line)
                log.flush()
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
    current_stage: str | None,
    model: str,
    thinking: str,
    started_at: str,
) -> dict[str, Any]:
    stages: list[dict[str, Any]] = []
    for stage in STAGES:
        path = _stage_report_path(run_root, stage)
        if not path.exists():
            stage_status = "pending"
            summary = None
        else:
            try:
                report = _validate_stage_report(path, stage)
                stage_status = report.get("status")
                summary = report.get("summary")
            except ValueError as exc:
                stage_status = "invalid_report"
                summary = str(exc)
        stages.append(
            {
                "id": stage.stage_id,
                "status": stage_status,
                "summary": summary,
                "report_path": str(path),
            }
        )
    phase05_status = None
    try:
        phase05_status = _load_object(_phase05_path(run_root), "Phase 05").get("status")
    except ValueError:
        phase05_status = "invalid"
    phase06_status = None
    if _phase06_path(run_root).exists():
        try:
            phase06_status = _load_object(_phase06_path(run_root), "Phase 06").get("status")
        except ValueError:
            phase06_status = "invalid"
    value = {
        "schema_version": 1,
        "kind": "procesio-control-tower-phase05-remediation-status",
        "project_id": PROJECT_ID,
        "remediation_id": REMEDIATION_ID,
        "state": state,
        "reason": reason,
        "current_stage": current_stage,
        "model": model,
        "thinking": thinking,
        "run_root": str(run_root),
        "started_at": started_at,
        "updated_at": _utc_now(),
        "stages": stages,
        "phase05_status": phase05_status,
        "phase06_status": phase06_status,
        "automatic_stage_retries": 0,
        "promotion_path": str(_remediation_root(run_root) / "promotion.json"),
        "final_report": str(run_root / "final-report.json"),
        "deployment_manifest": str(run_root / "deployment.json"),
    }
    _atomic_json(_remediation_root(run_root) / "status.json", value)
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=os.environ.get("PI_CONTROL_TOWER_MODEL", DEFAULT_MODEL))
    parser.add_argument("--thinking", default=os.environ.get("PI_CONTROL_TOWER_THINKING", DEFAULT_THINKING))
    parser.add_argument("--run-root", type=Path, default=DEFAULT_RUN_ROOT)
    parser.add_argument("--max-hours", type=float, default=8.0)
    parser.add_argument("--confirm", help=f"required exact value: {CONFIRMATION}")
    parser.add_argument("--interactive-approval", action="store_true", help="omit Pi --approve")
    parser.add_argument("--no-phase6", action="store_true", help="stop after promoting repaired Phase 05")
    parser.add_argument("--dry-run", action="store_true", help="print plan; no Pi or PROCESIO calls")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    started_at = _utc_now()
    model = str(args.model).strip()
    thinking = str(args.thinking).strip()
    run_root = args.run_root.expanduser().resolve()

    try:
        missing = [str(path) for path in _required_files() if not path.exists()]
        if missing:
            raise ValueError("required remediation files are missing: " + ", ".join(missing))
        if args.max_hours <= 0:
            raise ValueError("--max-hours must be positive")
        manifest = _load_object(MANIFEST, "project manifest")
        if manifest.get("project_id") != PROJECT_ID:
            raise ValueError("project manifest identity does not match this coordinator")
    except ValueError as exc:
        _emit({"error": {"code": "invalid_configuration", "message": str(exc), "details": {}}})
        return 2

    if args.dry_run:
        _emit(
            {
                "schema_version": 1,
                "dry_run": True,
                "project_id": PROJECT_ID,
                "remediation_id": REMEDIATION_ID,
                "model": model,
                "thinking": thinking,
                "run_root": str(run_root),
                "target": manifest["target"],
                "stages": [
                    {
                        "id": stage.stage_id,
                        "title": stage.title,
                        "mutation_scope": stage.mutation_scope,
                        "required_checks": list(stage.required_checks),
                        "budget_limits": stage.budget_limits,
                    }
                    for stage in STAGES
                ],
                "total_budget": TOTAL_BUDGET,
                "phase06_after_promotion": not args.no_phase6,
                "automatic_stage_retries": 0,
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
                    "message": f"Pass --confirm {CONFIRMATION} to authorize the bounded remediation.",
                    "details": {"project_id": PROJECT_ID, "remediation_id": REMEDIATION_ID},
                }
            }
        )
        return 2

    try:
        phase05_state, original_phase05 = _phase05_state(run_root)
    except ValueError as exc:
        _emit(
            {
                "error": {
                    "code": "phase05_not_remediable",
                    "message": str(exc),
                    "details": {"phase05_report": str(_phase05_path(run_root))},
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
        _remediation_root(run_root).mkdir(parents=True, exist_ok=True)
        metadata = _init_or_validate_metadata(
            run_root,
            model=model,
            thinking=thinking,
            original_phase05=original_phase05,
        )
    except (OSError, ValueError) as exc:
        _emit(
            {
                "error": {
                    "code": "resume_contract_mismatch",
                    "message": str(exc),
                    "details": {"run_root": str(run_root)},
                }
            }
        )
        return 2

    deadline = time.monotonic() + args.max_hours * 3600
    print(
        "PROCESIO Control Tower Phase 05 remediation\n"
        f"Model: {model}; thinking: {thinking}\n"
        "Target: pure-awesomeness / Internal-PROD / "
        "dc28053d-f701-4880-99c2-7d973899d135\n"
        f"Run root: {run_root}\n"
        f"Phase 05 state: {phase05_state}\n"
        f"Model inventory match: {model_lines[0] if model_lines else model}\n"
        "Automatic stage retries: 0",
        file=sys.stderr,
        flush=True,
    )

    reports: list[dict[str, Any]] = []
    if phase05_state != "promoted":
        for stage in STAGES:
            report_path = _stage_report_path(run_root, stage)
            if report_path.exists():
                try:
                    report = _validate_stage_report(report_path, stage)
                except ValueError as exc:
                    value = _status(
                        run_root,
                        state="error",
                        reason=f"invalid existing stage report: {exc}",
                        current_stage=stage.stage_id,
                        model=model,
                        thinking=thinking,
                        started_at=started_at,
                    )
                    _emit(value)
                    return 2
                if report.get("status") == "passed" and report.get("next_stage_safe") is True:
                    print(f"Skipping passed remediation stage {stage.stage_id}", file=sys.stderr)
                    reports.append(report)
                    continue
                value = _status(
                    run_root,
                    state="blocked",
                    reason=f"existing remediation stage is {report.get('status')!r}; inspect it before any rerun",
                    current_stage=stage.stage_id,
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
                    reason="wall-clock limit reached before the next remediation stage",
                    current_stage=stage.stage_id,
                    model=model,
                    thinking=thinking,
                    started_at=started_at,
                )
                _emit(value)
                return 75

            code = _run_stage(
                pi=pi,
                model=model,
                thinking=thinking,
                run_root=run_root,
                stage=stage,
                metadata=metadata,
                interactive_approval=args.interactive_approval,
                deadline=deadline,
            )
            if not report_path.exists():
                state = "paused" if code in (124, 130) else "unknown"
                value = _status(
                    run_root,
                    state=state,
                    reason=(
                        "stage stopped by wall-clock/operator before a report; reconcile before rerun"
                        if code in (124, 130)
                        else "Pi exited without a stage report; platform state may be partial or unknown"
                    ),
                    current_stage=stage.stage_id,
                    model=model,
                    thinking=thinking,
                    started_at=started_at,
                )
                value["child_exit_code"] = code
                _atomic_json(_remediation_root(run_root) / "status.json", value)
                _emit(value)
                return 75 if code in (124, 130) else 1
            try:
                report = _validate_stage_report(report_path, stage)
            except ValueError as exc:
                value = _status(
                    run_root,
                    state="error",
                    reason=f"new remediation stage report is invalid: {exc}",
                    current_stage=stage.stage_id,
                    model=model,
                    thinking=thinking,
                    started_at=started_at,
                )
                _emit(value)
                return 2
            if code != 0 or report.get("status") != "passed":
                value = _status(
                    run_root,
                    state="blocked" if report.get("status") in {"blocked", "failed"} else "unknown",
                    reason=(
                        f"stage ended with status {report.get('status')!r} and child exit {code}; "
                        "later stages were not started"
                    ),
                    current_stage=stage.stage_id,
                    model=model,
                    thinking=thinking,
                    started_at=started_at,
                )
                _emit(value)
                return 1
            reports.append(report)

        try:
            _promote_phase05(run_root, metadata=metadata, reports=reports)
        except (OSError, ValueError) as exc:
            value = _status(
                run_root,
                state="error",
                reason=f"remediation passed but Phase 05 promotion failed closed: {exc}",
                current_stage="promotion",
                model=model,
                thinking=thinking,
                started_at=started_at,
            )
            _emit(value)
            return 2
    else:
        for stage in STAGES:
            report = _validate_stage_report(_stage_report_path(run_root, stage), stage)
            if report.get("status") != "passed":
                raise ValueError("promoted Phase 05 is missing a passing remediation stage")
            reports.append(report)

    if args.no_phase6:
        value = _status(
            run_root,
            state="remediated",
            reason="all remediation stages passed and Phase 05 was promoted; Phase 06 was not requested",
            current_stage=None,
            model=model,
            thinking=thinking,
            started_at=started_at,
        )
        _emit(value)
        return 0

    remaining_seconds = max(0.0, deadline - time.monotonic())
    if remaining_seconds < 60:
        value = _status(
            run_root,
            state="paused",
            reason="Phase 05 was repaired, but too little wall-clock budget remained for Phase 06",
            current_stage=PHASE06_ID,
            model=model,
            thinking=thinking,
            started_at=started_at,
        )
        _emit(value)
        return 75

    phase06_code = _run_phase06(
        model=model,
        thinking=thinking,
        run_root=run_root,
        interactive_approval=args.interactive_approval,
        max_hours=remaining_seconds / 3600,
    )
    phase06_report = _phase06_path(run_root)
    final_report = run_root / "final-report.json"
    deployment = run_root / "deployment.json"
    if phase06_code == 0 and phase06_report.exists() and final_report.exists() and deployment.exists():
        value = _status(
            run_root,
            state="complete",
            reason="Phase 05 remediation passed, Phase 05 was promoted, and original Phase 06 completed",
            current_stage=None,
            model=model,
            thinking=thinking,
            started_at=started_at,
        )
        value["final_report_exists"] = True
        value["deployment_manifest_exists"] = True
        _atomic_json(_remediation_root(run_root) / "status.json", value)
        _emit(value)
        return 0

    value = _status(
        run_root,
        state="unknown" if phase06_code not in (124, 130) else "paused",
        reason=(
            "Phase 05 is repaired, but Phase 06 did not produce all required final artifacts; "
            "inspect the Phase 06 log/status before rerunning"
        ),
        current_stage=PHASE06_ID,
        model=model,
        thinking=thinking,
        started_at=started_at,
    )
    value["phase06_exit_code"] = phase06_code
    value["final_report_exists"] = final_report.exists()
    value["deployment_manifest_exists"] = deployment.exists()
    _atomic_json(_remediation_root(run_root) / "status.json", value)
    _emit(value)
    return 75 if phase06_code in (124, 130) else 1


if __name__ == "__main__":
    raise SystemExit(main())
