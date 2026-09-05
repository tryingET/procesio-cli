#!/usr/bin/env -S uv run --script
#
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Rotate the exposed Control Tower access token under a fixed security contract.

The launcher generates the replacement locally, freezes the operational skill package,
runs one bounded Pi remediation stage, validates its exact checks and execution budget,
scans artifacts for both clear tokens, replaces the protected token file, records new
Phase 05 security lineage, and invalidates pre-rotation Phase 06 artifacts. It never
retries the acting stage automatically after an ambiguous exit.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import shutil
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
PROJECT_DIR = ROOT / "examples" / "procesio" / "control-tower"
CONTRACT = PROJECT_DIR / "token-rotation.field-contract.md"
ORIGINAL_CONTRACT = PROJECT_DIR / "control-tower.field-contract.md"
PHASE05_CONTRACT = PROJECT_DIR / "phase05-remediation.field-contract.md"
MANIFEST = PROJECT_DIR / "control-tower.project.json"
SOURCE_SKILL = ROOT / "skills" / "procesio-cli"
SCHEDULE_HANDLER = ROOT / "tools" / "procesio" / "handlers" / "schedules.py"
SCHEDULE_SECURITY = ROOT / "tools" / "procesio" / "SCHEDULE-INPUT-SECURITY-NOTES.md"
DEFAULT_RUN_ROOT = ROOT / "scratchpad" / "procesio-control-tower-v1"
DEFAULT_MODEL = "zai/glm-5.3"
DEFAULT_THINKING = "high"
CONFIRMATION = "ROTATE_PROCESIO_CONTROL_TOWER_ACCESS_TOKEN_V1"
PROJECT_ID = "procesio-control-tower-v1"
REMEDIATION_ID = "control-tower-token-rotation-v1"
STAGE_ID = "05s-1-access-token-rotation"
PHASE05_ID = "05-mission-control-and-webhook-drill"
PHASE06_ID = "06-export-audit-and-acceptance"
PHASE05_REMEDIATION_ID = "control-tower-phase05-remediation-v1"

REQUIRED_CHECKS = (
    "exposure_acknowledged",
    "before_snapshots_and_digests_saved",
    "old_token_matches_current_ingest_hash",
    "new_token_staged_only_in_protected_file",
    "ingest_hash_updated_only",
    "schedule_input_updated_only",
    "ingest_and_schedule_valid",
    "old_token_denied_without_write",
    "new_token_accepted_and_row_unique",
    "complete_execution_tree_within_budget",
    "no_clear_token_in_agent_output_or_artifacts",
    "phase06_artifacts_identified_as_stale",
    "rotation_ready_for_host_finalization",
    "no_unknown_outcomes",
)
BUDGET = {
    "process_edits": 1,
    "schedule_edits": 1,
    "process_runs": 2,
    "process_instances": 3,
    "ledger_rows_created": 1,
    "form_submissions": 0,
    "webhook_launches": 0,
}
ALLOWED_STAGE_STATUSES = {"passed", "blocked", "unknown", "failed"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load(path: Path, label: str) -> dict[str, Any]:
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


def _atomic_bytes(path: Path, value: bytes, *, mode: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(value)
    if mode is not None:
        os.chmod(temporary, mode)
    temporary.replace(path)
    if mode is not None:
        os.chmod(path, mode)


def _emit(value: dict[str, Any]) -> None:
    print(json.dumps(value, ensure_ascii=False, separators=(",", ":")))


def _rotation_root(run_root: Path) -> Path:
    return run_root / "remediation" / "token-rotation"


def _token_path(run_root: Path) -> Path:
    return run_root / "form-access-token.txt"


def _new_token_path(run_root: Path) -> Path:
    return _rotation_root(run_root) / "new-form-access-token.txt"


def _metadata_path(run_root: Path) -> Path:
    return _rotation_root(run_root) / "metadata.json"


def _stage_path(run_root: Path) -> Path:
    return _rotation_root(run_root) / "stage.json"


def _log_path(run_root: Path) -> Path:
    return _rotation_root(run_root) / "stage.log"


def _attestation_path(run_root: Path) -> Path:
    return _rotation_root(run_root) / "attestation.json"


def _snapshot_root(run_root: Path) -> Path:
    return _rotation_root(run_root) / "frozen-skill" / "procesio-cli"


def _phase_path(run_root: Path, phase_id: str) -> Path:
    return run_root / "phases" / f"{phase_id}.json"


def _token_value(path: Path) -> bytes:
    try:
        value = path.read_text(encoding="utf-8").strip().encode("utf-8")
    except (OSError, UnicodeError) as exc:
        raise ValueError(f"protected token file is not readable: {path}: {exc}") from exc
    if len(value) < 16:
        raise ValueError(f"protected token file is empty or implausibly short: {path}")
    return value


def _mode_is_private(path: Path) -> bool:
    if os.name == "nt":
        return True
    return (path.stat().st_mode & 0o077) == 0


def _files(root: Path) -> list[Path]:
    return sorted(
        path
        for path in root.rglob("*")
        if path.is_file()
        and not path.is_symlink()
        and "__pycache__" not in path.parts
        and path.suffix not in {".pyc", ".pyo"}
    )


def _tree_fingerprint(root: Path) -> tuple[str, list[dict[str, Any]]]:
    digest = hashlib.sha256()
    records: list[dict[str, Any]] = []
    for path in _files(root):
        relative = path.relative_to(root).as_posix()
        content = path.read_bytes()
        encoded = relative.encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
        records.append(
            {
                "path": relative,
                "bytes": len(content),
                "sha256": _sha256_bytes(content),
            }
        )
    return digest.hexdigest(), records


def _snapshot_skill(run_root: Path) -> dict[str, Any]:
    snapshot = _snapshot_root(run_root)
    manifest_path = snapshot.parent / "skill-snapshot.json"
    if snapshot.exists() != manifest_path.exists():
        raise ValueError("partial rotation skill snapshot exists; preserve and inspect it")
    if not snapshot.exists():
        if not (SOURCE_SKILL / "SKILL.md").is_file():
            raise ValueError(f"source skill is missing: {SOURCE_SKILL}")
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        temporary = snapshot.with_name(snapshot.name + ".tmp")
        if temporary.exists():
            shutil.rmtree(temporary)
        shutil.copytree(SOURCE_SKILL, temporary)
        temporary.replace(snapshot)
        fingerprint, records = _tree_fingerprint(snapshot)
        value = {
            "schema_version": 1,
            "kind": "frozen-agent-skill-package",
            "source": str(SOURCE_SKILL.relative_to(ROOT)),
            "snapshot": str(snapshot),
            "fingerprint_sha256": fingerprint,
            "file_count": len(records),
            "files": records,
            "created_at": _utc_now(),
        }
        _atomic_json(manifest_path, value)
        return value
    value = _load(manifest_path, "rotation skill snapshot manifest")
    fingerprint, records = _tree_fingerprint(snapshot)
    if value.get("schema_version") != 1:
        raise ValueError("rotation skill snapshot manifest schema is invalid")
    if value.get("fingerprint_sha256") != fingerprint:
        raise ValueError("frozen rotation skill package changed; use a new reviewed run root")
    if value.get("file_count") != len(records):
        raise ValueError("frozen rotation skill package file count changed")
    return value


def _model_inventory(pi: str, model: str) -> tuple[bool, list[str], str]:
    provider, separator, model_name = model.partition("/")
    if not separator or not provider or not model_name:
        return False, [], "model must be an exact provider/model identifier"
    try:
        process = subprocess.run(
            [pi, "--list-models"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, [], f"could not list Pi models: {exc}"
    output = "\n".join(part for part in (process.stdout, process.stderr) if part)
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    exact = [
        line
        for line in lines
        if provider.casefold() in line.casefold()
        and model_name.casefold() in line.casefold()
    ]
    related = [line for line in lines if model_name.casefold() in line.casefold()][:12]
    if process.returncode:
        return False, related, f"pi --list-models exited {process.returncode}"
    if not exact:
        return False, related, f"Pi did not list exact model {model!r}"
    return True, exact[:4], ""


def _required_files() -> tuple[Path, ...]:
    return (
        CONTRACT,
        ORIGINAL_CONTRACT,
        PHASE05_CONTRACT,
        MANIFEST,
        SOURCE_SKILL / "SKILL.md",
        SCHEDULE_HANDLER,
        SCHEDULE_SECURITY,
    )


def _input_hashes() -> dict[str, str]:
    return {
        str(path.relative_to(ROOT)): _sha256(path)
        for path in _required_files()
    }


def _validate_phase05_for_rotation(run_root: Path) -> dict[str, Any]:
    report = _load(_phase_path(run_root, PHASE05_ID), "Phase 05 report")
    if report.get("schema_version") != 1:
        raise ValueError("Phase 05 report schema_version must be 1")
    if report.get("project_id") != PROJECT_ID or report.get("phase") != PHASE05_ID:
        raise ValueError("Phase 05 report identity does not match the Control Tower")
    if report.get("status") != "passed" or report.get("next_phase_safe") is not True:
        raise ValueError("Phase 05 must be functionally promoted before token rotation")
    remediation = report.get("remediation")
    if not isinstance(remediation, dict) or remediation.get("remediation_id") != PHASE05_REMEDIATION_ID:
        raise ValueError("Phase 05 does not contain the expected functional remediation lineage")
    if report.get("unknown_outcomes") not in ([], None):
        raise ValueError("Phase 05 still contains unknown outcomes")
    return report


def _new_token() -> bytes:
    return secrets.token_urlsafe(32).encode("ascii")


def _init_or_validate_metadata(
    run_root: Path,
    *,
    model: str,
    thinking: str,
    phase05: dict[str, Any],
    snapshot: dict[str, Any],
) -> dict[str, Any]:
    path = _metadata_path(run_root)
    token_path = _token_path(run_root)
    new_path = _new_token_path(run_root)
    if not token_path.is_file():
        raise ValueError(f"current protected token is missing: {token_path}")
    if not _mode_is_private(token_path):
        raise ValueError(f"current protected token is not private: {token_path}")

    if path.exists():
        metadata = _load(path, "token rotation metadata")
        expected = {
            "schema_version": 1,
            "project_id": PROJECT_ID,
            "remediation_id": REMEDIATION_ID,
            "stage": STAGE_ID,
            "model": model,
            "thinking": thinking,
            "input_hashes": _input_hashes(),
            "skill_fingerprint_sha256": snapshot.get("fingerprint_sha256"),
            "phase05_sha256": metadata.get("phase05_sha256"),
            "budget": BUDGET,
        }
        for key, value in expected.items():
            if metadata.get(key) != value:
                raise ValueError(
                    f"cannot resume token rotation: metadata field {key!r} changed"
                )
        for key in ("old_token_sha256", "new_token_sha256", "evidence_key"):
            if not isinstance(metadata.get(key), str) or not metadata[key]:
                raise ValueError(f"token rotation metadata is missing {key}")
        current_hash = _sha256_bytes(_token_value(token_path))
        new_exists = new_path.is_file()
        if current_hash == metadata["old_token_sha256"]:
            if not new_exists:
                raise ValueError("replacement token staging file is missing")
            if not _mode_is_private(new_path):
                raise ValueError("replacement token staging file is not private")
            if _sha256_bytes(_token_value(new_path)) != metadata["new_token_sha256"]:
                raise ValueError("replacement token staging file changed")
        elif current_hash == metadata["new_token_sha256"]:
            if new_exists:
                raise ValueError("token file is rotated but stale staging file still exists")
        else:
            raise ValueError("protected token no longer matches old or replacement hash")
        return metadata

    root = _rotation_root(run_root)
    root.mkdir(parents=True, exist_ok=True)
    if new_path.exists():
        raise ValueError("replacement token exists without metadata; preserve and inspect it")
    old = _token_value(token_path)
    new = _new_token()
    while new == old:
        new = _new_token()
    _atomic_bytes(new_path, new + b"\n", mode=0o600)
    phase05_path = _phase_path(run_root, PHASE05_ID)
    metadata = {
        "schema_version": 1,
        "kind": "procesio-control-tower-token-rotation-metadata",
        "project_id": PROJECT_ID,
        "remediation_id": REMEDIATION_ID,
        "stage": STAGE_ID,
        "model": model,
        "thinking": thinking,
        "target": {
            "profile": "pure-awesomeness",
            "environment": "Internal-PROD",
            "workspace_id": "dc28053d-f701-4880-99c2-7d973899d135",
        },
        "input_hashes": _input_hashes(),
        "skill_snapshot": str(_snapshot_root(run_root)),
        "skill_fingerprint_sha256": snapshot.get("fingerprint_sha256"),
        "phase05_path": str(phase05_path),
        "phase05_sha256": _sha256(phase05_path),
        "old_token_path": str(token_path),
        "new_token_path": str(new_path),
        "old_token_sha256": _sha256_bytes(old),
        "new_token_sha256": _sha256_bytes(new),
        "evidence_key": f"control-tower:token-rotation:{uuid.uuid4()}",
        "budget": dict(BUDGET),
        "created_at": _utc_now(),
        "known_incident": {
            "kind": "clear_token_printed_to_agent_transcript",
            "redaction_erases_incident": False,
            "requires_revocation": True,
        },
    }
    _atomic_json(path, metadata)
    return metadata


def _prompt(run_root: Path, metadata: dict[str, Any]) -> str:
    return f"""You are executing one separately approved security-remediation stage for a real PROCESIO project.

Project: {PROJECT_ID}
Remediation: {REMEDIATION_ID}
Stage: {STAGE_ID}
Exact report path: {_stage_path(run_root)}
Rotation root: {_rotation_root(run_root)}

Read before acting:
- {CONTRACT}
- {ORIGINAL_CONTRACT}
- {PHASE05_CONTRACT}
- {MANIFEST}
- {_phase_path(run_root, PHASE05_ID)}
- {run_root / 'remediation' / 'phase05' / 'stages' / '05r-2-whole-body-webhook.json'}
- {run_root / 'remediation' / 'phase05' / 'stages' / '05r-3-reconcile-and-promote.json'}
- {_snapshot_root(run_root) / 'SKILL.md'}
- {SCHEDULE_SECURITY}

Target every PROCESIO call with profile pure-awesomeness, environment Internal-PROD,
and workspace ID dc28053d-f701-4880-99c2-7d973899d135.

The old token was exposed in an agent transcript. Acknowledge that fact; do not claim
redaction erased it. Rotate it under the committed contract.

Protected files (paths only; never print their contents):
- old token: {_token_path(run_root)}
- replacement token: {_new_token_path(run_root)}
Old token SHA-256: {metadata['old_token_sha256']}
Replacement token SHA-256: {metadata['new_token_sha256']}
Stable evidence key: {metadata['evidence_key']}

Use secret-bearing payload files with mode 0600 and pass them by @file. Do not place a
token in a visible command, tool argument, report, log, screenshot, or ordinary file.
Use get-schedule --redact-process-inputs for all schedule reads. Raw schedule reads are
forbidden in this stage.

Authorized exact budget:
{json.dumps(BUDGET, indent=2, sort_keys=True)}

The passing report must contain these check IDs exactly once, in this order, each with
passed=true and direct secret-free evidence:
{json.dumps(list(REQUIRED_CHECKS), indent=2)}

There are no automatic retries. Reconcile a lost write or run response by stable ID,
instance window, and the fixed evidence key, then stop unless the outcome is proved.
Do not submit the form, launch a webhook, let the schedule fire, create a resource, or
change anything outside the ingest expected-token hash and the retained schedule's
bound access-token value.

Write the exact report schema from the rotation contract atomically to
{_stage_path(run_root)}. Allowed statuses are passed, blocked, unknown, or failed;
passed_with_gap is forbidden. Do not replace the protected current token file or edit
phase/export reports; host code performs finalization only after validating your report
and scanning for clear-token leakage. Then print a compact secret-free summary.
"""


def _run_stage(
    *,
    pi: str,
    model: str,
    thinking: str,
    run_root: Path,
    metadata: dict[str, Any],
    interactive: bool,
    deadline: float,
) -> int:
    if time.monotonic() >= deadline:
        return 124
    command = [pi, "-p", "--no-session", "--no-skills"]
    if not interactive:
        command.append("--approve")
    command += [
        "--model", model,
        "--models", model,
        "--thinking", thinking,
        "--skill", str(_snapshot_root(run_root)),
        "--",
        _prompt(run_root, metadata),
    ]
    log_path = _log_path(run_root)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    print(
        "\n=== 05s-1-access-token-rotation: revoke exposed token ===\n"
        f"Model: {model}; thinking: {thinking}\n"
        f"Report: {_stage_path(run_root)}\n"
        f"Log: {log_path}",
        file=sys.stderr,
        flush=True,
    )
    with log_path.open("a", encoding="utf-8") as log:
        log.write(f"\n--- invocation {_utc_now()} ---\n")
        log.flush()
        try:
            process = subprocess.Popen(
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
        assert process.stdout is not None
        try:
            for line in process.stdout:
                sys.stdout.write(line)
                sys.stdout.flush()
                log.write(line)
                log.flush()
                if time.monotonic() >= deadline and process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=20)
                    except subprocess.TimeoutExpired:
                        process.kill()
                    log.write("token rotation deadline reached\n")
                    return 124
        except KeyboardInterrupt:
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                process.kill()
            return 130
        return int(process.wait())


def _validate_stage_report(path: Path, metadata: dict[str, Any]) -> dict[str, Any]:
    report = _load(path, "token rotation stage report")
    expected_fields = {
        "schema_version": 1,
        "project_id": PROJECT_ID,
        "remediation_id": REMEDIATION_ID,
        "stage": STAGE_ID,
    }
    for key, value in expected_fields.items():
        if report.get(key) != value:
            raise ValueError(f"{path}: expected {key}={value!r}")
    status = report.get("status")
    if status not in ALLOWED_STAGE_STATUSES:
        raise ValueError(f"{path}: unsupported status {status!r}; passed_with_gap is forbidden")

    checks = report.get("checks")
    if not isinstance(checks, list):
        raise ValueError(f"{path}: checks must be a list")
    observed: list[str] = []
    for item in checks:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            raise ValueError(f"{path}: every check must have a string id")
        observed.append(item["id"])
    if len(observed) != len(set(observed)):
        raise ValueError(f"{path}: duplicate check ids")

    usage = report.get("budget_usage")
    if not isinstance(usage, dict):
        raise ValueError(f"{path}: budget_usage must be an object")
    for key, expected in BUDGET.items():
        value = usage.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{path}: budget_usage.{key} must be a non-negative integer")
        if value > expected:
            raise ValueError(f"{path}: budget_usage.{key}={value} exceeds {expected}")

    rotation = report.get("token_rotation")
    if not isinstance(rotation, dict):
        raise ValueError(f"{path}: token_rotation must be an object")
    for key, expected in {
        "old_sha256": metadata["old_token_sha256"],
        "new_sha256": metadata["new_token_sha256"],
        "evidence_key": metadata["evidence_key"],
        "ingest_process_id": "d46af04c-7cc7-4777-ad0e-dd049ad58a8b",
    }.items():
        if rotation.get(key) != expected:
            raise ValueError(f"{path}: token_rotation.{key} does not match frozen metadata")
    for key in (
        "schedule_id",
        "old_token_instance_id",
        "ledger_row_identity",
    ):
        if not isinstance(rotation.get(key), str) or not rotation[key]:
            raise ValueError(f"{path}: token_rotation.{key} is missing")
    new_instances = rotation.get("new_token_instance_ids")
    if not isinstance(new_instances, list) or len(new_instances) != 2 or not all(
        isinstance(item, str) and item for item in new_instances
    ):
        raise ValueError(f"{path}: new_token_instance_ids must contain ingest and child ids")

    if status == "passed":
        if observed != list(REQUIRED_CHECKS):
            raise ValueError(
                f"{path}: passing check ids/order differ from fixed contract; "
                f"expected {list(REQUIRED_CHECKS)!r}, observed {observed!r}"
            )
        for item in checks:
            if item.get("passed") is not True:
                raise ValueError(f"{path}: passing report contains failed check {item['id']!r}")
            if item.get("evidence") in (None, "", [], {}):
                raise ValueError(f"{path}: check {item['id']!r} has no evidence")
        if usage != BUDGET:
            raise ValueError(f"{path}: passing budget must equal the fixed usage {BUDGET!r}")
        if report.get("gaps") not in ([], None):
            raise ValueError(f"{path}: passing security remediation cannot retain gaps")
        if report.get("unknown_outcomes") not in ([], None):
            raise ValueError(f"{path}: passing security remediation has unknown outcomes")
        if report.get("next_stage_safe") is not True:
            raise ValueError(f"{path}: passing report requires next_stage_safe=true")
    return report


def _bytes_contain(path: Path, needles: Iterable[bytes]) -> list[str]:
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ValueError(f"cannot scan artifact {path}: {exc}") from exc
    return [name for name, needle in (("old", next(iter(needles), b"")),) if False]


def _scan_token_leaks(
    run_root: Path,
    *,
    old_token: bytes,
    new_token: bytes,
    excluded: set[Path],
) -> list[dict[str, str]]:
    excluded_resolved = {path.resolve() for path in excluded}
    hits: list[dict[str, str]] = []
    for path in sorted(run_root.rglob("*")):
        if not path.is_file() or path.is_symlink() or path.resolve() in excluded_resolved:
            continue
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise ValueError(f"cannot scan artifact {path}: {exc}") from exc
        if old_token in data:
            hits.append({"path": str(path), "token": "old"})
        if new_token in data:
            hits.append({"path": str(path), "token": "new"})
    return hits


def _validate_scan_record(path: Path, metadata: dict[str, Any]) -> dict[str, Any]:
    record = _load(path, "host token scan")
    expected = {
        "schema_version": 1,
        "kind": "control-tower-token-leak-scan",
        "old_token_sha256": metadata["old_token_sha256"],
        "new_token_sha256": metadata["new_token_sha256"],
        "hits": [],
    }
    for key, value in expected.items():
        if record.get(key) != value:
            raise ValueError(f"host token scan field {key!r} is invalid")
    return record


def _host_scan_before_replace(
    run_root: Path,
    metadata: dict[str, Any],
) -> tuple[dict[str, Any], bytes | None, bytes]:
    scan_path = _rotation_root(run_root) / "host-secret-scan.json"
    token_path = _token_path(run_root)
    new_path = _new_token_path(run_root)
    current = _token_value(token_path)
    current_hash = _sha256_bytes(current)
    if scan_path.exists():
        record = _validate_scan_record(scan_path, metadata)
        if current_hash == metadata["old_token_sha256"]:
            if not new_path.is_file():
                raise ValueError("replacement staging file is missing after host scan")
            new = _token_value(new_path)
            if _sha256_bytes(new) != metadata["new_token_sha256"]:
                raise ValueError("replacement staging token changed after host scan")
            return record, current, new
        if current_hash == metadata["new_token_sha256"] and not new_path.exists():
            return record, None, current
        raise ValueError("token files do not match the resumable host-scan state")

    if current_hash != metadata["old_token_sha256"]:
        raise ValueError("host scan is missing but current token is no longer the old token")
    if not new_path.is_file():
        raise ValueError("replacement staging token is missing")
    new = _token_value(new_path)
    if _sha256_bytes(new) != metadata["new_token_sha256"]:
        raise ValueError("replacement staging token does not match metadata")
    hits = _scan_token_leaks(
        run_root,
        old_token=current,
        new_token=new,
        excluded={token_path, new_path},
    )
    if hits:
        raise ValueError(
            "clear token found outside protected token files: "
            + json.dumps(hits, ensure_ascii=False)
        )
    record = {
        "schema_version": 1,
        "kind": "control-tower-token-leak-scan",
        "project_id": PROJECT_ID,
        "remediation_id": REMEDIATION_ID,
        "old_token_sha256": metadata["old_token_sha256"],
        "new_token_sha256": metadata["new_token_sha256"],
        "excluded_paths": [str(token_path), str(new_path)],
        "hits": [],
        "scanned_at": _utc_now(),
    }
    _atomic_json(scan_path, record)
    return record, current, new


def _replace_token_file(run_root: Path, metadata: dict[str, Any], new_token: bytes) -> None:
    token_path = _token_path(run_root)
    new_path = _new_token_path(run_root)
    current_hash = _sha256_bytes(_token_value(token_path))
    if current_hash == metadata["new_token_sha256"] and not new_path.exists():
        if not _mode_is_private(token_path):
            os.chmod(token_path, 0o600)
        return
    if current_hash != metadata["old_token_sha256"]:
        raise ValueError("cannot replace token: current token hash is neither old nor new")
    if not new_path.is_file() or _sha256_bytes(_token_value(new_path)) != metadata["new_token_sha256"]:
        raise ValueError("cannot replace token: staged replacement is missing or changed")
    if _sha256_bytes(new_token) != metadata["new_token_sha256"]:
        raise ValueError("in-memory replacement token does not match metadata")
    os.chmod(new_path, 0o600)
    new_path.replace(token_path)
    os.chmod(token_path, 0o600)


def _copy_immutable(source: Path, destination: Path) -> bytes:
    data = source.read_bytes()
    if destination.exists():
        if destination.read_bytes() != data:
            raise ValueError(f"archive collision: {destination}")
        return data
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_bytes(data)
    temporary.replace(destination)
    return data


def _promote_security_lineage(
    run_root: Path,
    *,
    metadata: dict[str, Any],
    report: dict[str, Any],
) -> dict[str, Any]:
    phase_path = _phase_path(run_root, PHASE05_ID)
    current = _load(phase_path, "Phase 05 report before security finalization")
    existing = current.get("security_remediation")
    if isinstance(existing, dict) and existing.get("remediation_id") == REMEDIATION_ID:
        if existing.get("new_token_sha256") != metadata["new_token_sha256"]:
            raise ValueError("existing Phase 05 security lineage belongs to another token")
        return current
    if _sha256(phase_path) != metadata["phase05_sha256"]:
        raise ValueError("Phase 05 report changed after rotation metadata was frozen")

    archive = _rotation_root(run_root) / "archive" / "phase05-pre-security-rotation.json"
    original_bytes = _copy_immutable(phase_path, archive)
    namespaced_checks = [
        {
            **item,
            "id": f"{STAGE_ID}:{item['id']}",
            "security_remediation_stage": STAGE_ID,
        }
        for item in report.get("checks") or []
    ]
    promoted = dict(current)
    promoted.update(
        {
            "status": "passed",
            "summary": (
                "Phase 05 functional remediation remains passed. A later security "
                "review correctly classified the clear-token transcript output as an "
                "exposure; the credential was separately rotated, the old token was "
                "rejected, the replacement succeeded, and pre-rotation Phase 06 "
                "artifacts were invalidated for a fresh audit."
            ),
            "unknown_outcomes": [],
            "next_phase_safe": True,
            "checks": (current.get("checks") or []) + namespaced_checks,
            "security_remediation": {
                "remediation_id": REMEDIATION_ID,
                "contract": str(CONTRACT.relative_to(ROOT)),
                "approved_confirmation": CONFIRMATION,
                "incident": "clear_token_printed_to_agent_transcript",
                "redaction_erased_incident": False,
                "old_token_revoked": True,
                "replacement_token_proven": True,
                "old_token_sha256": metadata["old_token_sha256"],
                "new_token_sha256": metadata["new_token_sha256"],
                "evidence_key": metadata["evidence_key"],
                "stage_report": str(_stage_path(run_root)),
                "original_phase05_archive": str(archive),
                "original_phase05_sha256": _sha256_bytes(original_bytes),
                "finalized_at": _utc_now(),
            },
        }
    )
    _atomic_json(phase_path, promoted)
    return promoted


def _archive_and_remove(source: Path, destination: Path) -> dict[str, Any] | None:
    if not source.exists():
        if destination.exists() and destination.is_file():
            data = destination.read_bytes()
            return {
                "source": str(source),
                "archive": str(destination),
                "bytes": len(data),
                "sha256": _sha256_bytes(data),
            }
        return None
    if not source.is_file():
        raise ValueError(f"expected a file while archiving Phase 06 state: {source}")
    data = source.read_bytes()
    if destination.exists():
        if not destination.is_file() or destination.read_bytes() != data:
            raise ValueError(f"Phase 06 archive collision: {destination}")
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        temporary.write_bytes(data)
        temporary.replace(destination)
    source.unlink()
    return {
        "source": str(source),
        "archive": str(destination),
        "bytes": len(data),
        "sha256": _sha256_bytes(data),
    }


def _archive_phase06_state(run_root: Path) -> list[dict[str, Any]]:
    archive_root = _rotation_root(run_root) / "archive" / "pre-rotation-phase06"
    sources = [
        _phase_path(run_root, PHASE06_ID),
        run_root / "final-report.json",
        run_root / "deployment.json",
        run_root / "coordinator-status.json",
    ]
    export_root = run_root / "export"
    if export_root.is_dir():
        sources.extend(path for path in sorted(export_root.rglob("*")) if path.is_file())
    scope_root = run_root / "remediation" / "phase06-status-scope"
    if scope_root.is_dir():
        sources.extend(path for path in sorted(scope_root.rglob("*")) if path.is_file())

    records: list[dict[str, Any]] = []
    for source in sources:
        try:
            relative = source.relative_to(run_root)
        except ValueError as exc:
            raise ValueError(f"stale artifact escapes run root: {source}") from exc
        record = _archive_and_remove(source, archive_root / relative)
        if record:
            records.append(record)
    for directory in (scope_root, export_root):
        if directory.is_dir():
            for child in sorted(directory.rglob("*"), reverse=True):
                if child.is_dir():
                    try:
                        child.rmdir()
                    except OSError:
                        pass
            try:
                directory.rmdir()
            except OSError:
                pass
    return records


def _validate_attestation(path: Path) -> dict[str, Any]:
    value = _load(path, "token rotation attestation")
    expected = {
        "schema_version": 1,
        "kind": "procesio-control-tower-token-rotation-attestation",
        "project_id": PROJECT_ID,
        "remediation_id": REMEDIATION_ID,
        "stage": STAGE_ID,
        "status": "passed",
        "redaction_erased_incident": False,
        "old_token_revoked": True,
        "replacement_token_proven": True,
        "secret_scan_clean": True,
        "phase05_security_lineage_updated": True,
        "phase06_artifacts_invalidated": True,
    }
    for key, expected_value in expected.items():
        if value.get(key) != expected_value:
            raise ValueError(f"token rotation attestation field {key!r} is invalid")
    return value


def _finalize(
    run_root: Path,
    *,
    metadata: dict[str, Any],
    report: dict[str, Any],
) -> dict[str, Any]:
    attestation_path = _attestation_path(run_root)
    if attestation_path.exists():
        return _validate_attestation(attestation_path)

    scan, old_token, new_token = _host_scan_before_replace(run_root, metadata)
    _replace_token_file(run_root, metadata, new_token)
    phase05 = _promote_security_lineage(run_root, metadata=metadata, report=report)
    stale = _archive_phase06_state(run_root)

    # After replacement, only the designated current token file may contain the new
    # value. The old-token scan was fixed before replacement and is immutable.
    post_hits = _scan_token_leaks(
        run_root,
        old_token=old_token or b"__old_token_unavailable_after_resumed_replace__",
        new_token=new_token,
        excluded={_token_path(run_root)},
    )
    if post_hits:
        raise ValueError(
            "clear token found after host finalization: "
            + json.dumps(post_hits, ensure_ascii=False)
        )
    if _sha256_bytes(_token_value(_token_path(run_root))) != metadata["new_token_sha256"]:
        raise ValueError("protected local token does not contain the replacement")
    if not _mode_is_private(_token_path(run_root)):
        raise ValueError("protected local token permissions are not private")
    if _phase_path(run_root, PHASE06_ID).exists():
        raise ValueError("pre-rotation Phase 06 report was not invalidated")
    if (run_root / "final-report.json").exists() or (run_root / "deployment.json").exists():
        raise ValueError("pre-rotation final artifacts were not invalidated")

    attestation = {
        "schema_version": 1,
        "kind": "procesio-control-tower-token-rotation-attestation",
        "project_id": PROJECT_ID,
        "remediation_id": REMEDIATION_ID,
        "stage": STAGE_ID,
        "status": "passed",
        "contract": str(CONTRACT.relative_to(ROOT)),
        "approved_confirmation": CONFIRMATION,
        "incident": "clear_token_printed_to_agent_transcript",
        "redaction_erased_incident": False,
        "old_token_revoked": True,
        "replacement_token_proven": True,
        "old_token_sha256": metadata["old_token_sha256"],
        "new_token_sha256": metadata["new_token_sha256"],
        "evidence_key": metadata["evidence_key"],
        "budget_usage": report["budget_usage"],
        "stage_report": str(_stage_path(run_root)),
        "host_secret_scan": str(_rotation_root(run_root) / "host-secret-scan.json"),
        "host_secret_scan_sha256": _sha256(_rotation_root(run_root) / "host-secret-scan.json"),
        "secret_scan_clean": scan.get("hits") == [] and post_hits == [],
        "current_token_path": str(_token_path(run_root)),
        "current_token_mode_private": _mode_is_private(_token_path(run_root)),
        "phase05_security_lineage_updated": isinstance(
            phase05.get("security_remediation"), dict
        ),
        "phase05_report": str(_phase_path(run_root, PHASE05_ID)),
        "phase05_report_sha256": _sha256(_phase_path(run_root, PHASE05_ID)),
        "phase06_artifacts_invalidated": True,
        "archived_stale_artifacts": stale,
        "next_required_action": "rerun_phase06_from_rotated_state",
        "platform_calls_by_host": 0,
        "model_calls_by_host": 0,
        "finalized_at": _utc_now(),
    }
    _atomic_json(attestation_path, attestation)
    return _validate_attestation(attestation_path)


def _status(
    run_root: Path,
    *,
    state: str,
    reason: str,
    model: str,
    thinking: str,
    child_exit_code: int | None = None,
) -> dict[str, Any]:
    value = {
        "schema_version": 1,
        "kind": "procesio-control-tower-token-rotation-status",
        "project_id": PROJECT_ID,
        "remediation_id": REMEDIATION_ID,
        "stage": STAGE_ID,
        "state": state,
        "reason": reason,
        "model": model,
        "thinking": thinking,
        "run_root": str(run_root),
        "stage_report": str(_stage_path(run_root)),
        "attestation": str(_attestation_path(run_root)),
        "automatic_stage_retries": 0,
        "updated_at": _utc_now(),
    }
    if child_exit_code is not None:
        value["child_exit_code"] = child_exit_code
    _atomic_json(_rotation_root(run_root) / "status.json", value)
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=os.environ.get("PI_CONTROL_TOWER_MODEL", DEFAULT_MODEL))
    parser.add_argument("--thinking", default=os.environ.get("PI_CONTROL_TOWER_THINKING", DEFAULT_THINKING))
    parser.add_argument("--run-root", type=Path, default=DEFAULT_RUN_ROOT)
    parser.add_argument("--max-hours", type=float, default=2.0)
    parser.add_argument("--confirm", help=f"required exact value: {CONFIRMATION}")
    parser.add_argument("--interactive-approval", action="store_true", help="omit Pi --approve")
    parser.add_argument("--dry-run", action="store_true", help="print fixed plan without generating a token or calling Pi")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    model = str(args.model).strip()
    thinking = str(args.thinking).strip()
    run_root = args.run_root.expanduser().resolve()

    try:
        missing = [str(path) for path in _required_files() if not path.exists()]
        if missing:
            raise ValueError("required rotation files are missing: " + ", ".join(missing))
        if args.max_hours <= 0:
            raise ValueError("--max-hours must be positive")
        manifest = _load(MANIFEST, "project manifest")
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
                "stage": STAGE_ID,
                "model": model,
                "thinking": thinking,
                "run_root": str(run_root),
                "required_checks": list(REQUIRED_CHECKS),
                "budget": BUDGET,
                "confirmation_required": CONFIRMATION,
                "automatic_stage_retries": 0,
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
                    "message": f"Pass --confirm {CONFIRMATION} to authorize token rotation.",
                    "details": {"project_id": PROJECT_ID, "remediation_id": REMEDIATION_ID},
                }
            }
        )
        return 2

    if _attestation_path(run_root).exists():
        try:
            attestation = _validate_attestation(_attestation_path(run_root))
        except ValueError as exc:
            _emit({"error": {"code": "invalid_existing_attestation", "message": str(exc), "details": {}}})
            return 2
        _emit(
            {
                "schema_version": 1,
                "state": "complete",
                "reason": "token rotation already passed",
                "attestation": str(_attestation_path(run_root)),
                "new_token_sha256": attestation.get("new_token_sha256"),
                "next_required_action": "rerun_phase06_from_rotated_state",
            }
        )
        return 0

    try:
        phase05 = _validate_phase05_for_rotation(run_root)
        snapshot = _snapshot_skill(run_root)
        metadata = _init_or_validate_metadata(
            run_root,
            model=model,
            thinking=thinking,
            phase05=phase05,
            snapshot=snapshot,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        _emit({"error": {"code": "rotation_setup_failed", "message": str(exc), "details": {"run_root": str(run_root)}}})
        return 2

    if not _stage_path(run_root).exists():
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
                        "details": {"requested_model": model, "related_model_lines": model_lines},
                    }
                }
            )
            return 2
        deadline = time.monotonic() + args.max_hours * 3600
        code = _run_stage(
            pi=pi,
            model=model,
            thinking=thinking,
            run_root=run_root,
            metadata=metadata,
            interactive=args.interactive_approval,
            deadline=deadline,
        )
        if code != 0:
            state = "paused" if code in (124, 130) else "unknown"
            reason = (
                "rotation stage stopped; reconcile platform state before resuming"
                if code in (124, 130)
                else "Pi exited without a verified passing report; mutation outcome may be partial"
            )
            value = _status(
                run_root,
                state=state,
                reason=reason,
                model=model,
                thinking=thinking,
                child_exit_code=code,
            )
            _emit(value)
            return 75 if code in (124, 130) else 1
        if not _stage_path(run_root).exists():
            value = _status(
                run_root,
                state="unknown",
                reason="Pi exited successfully without writing the required stage report",
                model=model,
                thinking=thinking,
            )
            _emit(value)
            return 1

    try:
        report = _validate_stage_report(_stage_path(run_root), metadata)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        value = _status(
            run_root,
            state="error",
            reason=f"stage report is invalid: {exc}",
            model=model,
            thinking=thinking,
        )
        _emit(value)
        return 2
    if report.get("status") != "passed":
        value = _status(
            run_root,
            state="blocked",
            reason=f"rotation stage ended with status {report.get('status')!r}",
            model=model,
            thinking=thinking,
        )
        _emit(value)
        return 1

    try:
        attestation = _finalize(run_root, metadata=metadata, report=report)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        value = _status(
            run_root,
            state="error",
            reason=f"host finalization failed closed: {exc}",
            model=model,
            thinking=thinking,
        )
        _emit(value)
        return 2

    value = _status(
        run_root,
        state="complete",
        reason="exposed token revoked and replacement proven; rerun Phase 06",
        model=model,
        thinking=thinking,
    )
    value.update(
        {
            "attestation": str(_attestation_path(run_root)),
            "old_token_revoked": attestation["old_token_revoked"],
            "replacement_token_proven": attestation["replacement_token_proven"],
            "phase06_artifacts_invalidated": attestation["phase06_artifacts_invalidated"],
            "next_required_action": "rerun_phase06_from_rotated_state",
        }
    )
    _atomic_json(_rotation_root(run_root) / "status.json", value)
    _emit(value)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
