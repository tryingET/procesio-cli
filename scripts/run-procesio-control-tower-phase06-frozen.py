#!/usr/bin/env -S uv run --script
#
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Run Control Tower Phase 06 with the frozen remediation skill package.

The helper also repairs one fail-closed reporting error without re-running work:
when Phase 06 completed all of its own checks but copied Phase 03's approved connector
fallback into its phase status, host code archives the report and scopes Phase 06 to
``passed`` while retaining the aggregate project ``passed_with_gap`` verdict.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
ORIGINAL = ROOT / "scripts" / "run-procesio-control-tower.py"
DEFAULT_RUN_ROOT = ROOT / "scratchpad" / "procesio-control-tower-v1"
DEFAULT_SKILL_ROOT = DEFAULT_RUN_ROOT / "remediation/phase05/frozen-skill/procesio-cli"
CONFIRMATION = "FINISH_PROCESIO_CONTROL_TOWER_V1_PHASE06"
ORIGINAL_CONFIRMATION = "BUILD_PROCESIO_CONTROL_TOWER_V1"
PROJECT_ID = "procesio-control-tower-v1"
PHASE03_ID = "03-github-connector-and-pulse"
PHASE05_ID = "05-mission-control-and-webhook-drill"
PHASE06_ID = "06-export-audit-and-acceptance"
NORMALIZATION_RELATIVE = Path("remediation/phase06-status-scope")


def _load_original():
    spec = importlib.util.spec_from_file_location(
        "run_procesio_control_tower_original", ORIGINAL
    )
    if spec is None or spec.loader is None:
        raise ValueError(f"cannot import original coordinator: {ORIGINAL}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _install_execution_skill(module, skill_root: Path) -> None:
    """Use the frozen package for execution while preserving old metadata identity."""
    original_skill = module.SKILL
    original_metadata_value = module._metadata_value
    original_prompt = module._prompt
    if not (skill_root / "SKILL.md").is_file():
        raise ValueError(f"frozen skill root is invalid: {skill_root}")
    if not (original_skill / "SKILL.md").is_file():
        raise ValueError(f"original skill root is invalid: {original_skill}")

    def metadata_value(model: str, thinking: str):
        active = module.SKILL
        module.SKILL = original_skill
        try:
            return original_metadata_value(model, thinking)
        finally:
            module.SKILL = active

    def required_files():
        return (
            module.CONTRACT,
            module.MANIFEST,
            module.SEEDS,
            module.OPENAPI,
            original_skill / "SKILL.md",
            skill_root / "SKILL.md",
        )

    def prompt(run_root: Path, phase):
        text = original_prompt(run_root, phase)
        if getattr(phase, "phase_id", None) == PHASE06_ID:
            text += """

Phase-status scope for the final audit:
- Judge Phase 06 only from its own required checks and outcomes.
- Phase 03's approved connector fallback remains an inherited project gap. Keep it in
  final/project gap lineage, not in Phase 06's status or Phase 06 `gaps`.
- Use `status: passed` when Phase 06 has no new local gap. A new Phase 06 gap is
  blocking because this phase is not authorized to use `passed_with_gap`.
"""
        return text

    module._metadata_value = metadata_value
    module._required_files = required_files
    module._prompt = prompt
    module.SKILL = skill_root


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--thinking", required=True)
    parser.add_argument("--run-root", type=Path, default=DEFAULT_RUN_ROOT)
    parser.add_argument("--skill-root", type=Path, default=DEFAULT_SKILL_ROOT)
    parser.add_argument("--max-hours", type=float, required=True)
    parser.add_argument("--confirm")
    parser.add_argument("--interactive-approval", action="store_true")
    return parser


def _load(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not readable JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must contain one JSON object")
    return value


def _write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _archive(source: Path, destination: Path) -> bytes:
    data = source.read_bytes()
    if destination.exists() and destination.read_bytes() != data:
        raise ValueError(f"archive collision at {destination}")
    if not destination.exists():
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        temporary.write_bytes(data)
        temporary.replace(destination)
    return data


def _gap_text(value: Any) -> str:
    raw = value if isinstance(value, str) else json.dumps(value, sort_keys=True)
    return " ".join(raw.casefold().replace("_", "-").split())


def _connector_fallback(value: Any) -> bool:
    text = _gap_text(value)
    connector = any(x in text for x in ("connector", "custom action", "call api"))
    fallback = any(x in text for x in ("fallback", "unavailable", "not built"))
    return connector and fallback


def _validate_lineage(report: dict[str, Any], phase: str, status: str) -> None:
    expected = {
        "schema_version": 1,
        "project_id": PROJECT_ID,
        "phase": phase,
        "status": status,
        "next_phase_safe": True,
    }
    for key, value in expected.items():
        if report.get(key) != value:
            raise ValueError(f"{phase}: expected {key}={value!r}")
    if report.get("unknown_outcomes") != []:
        raise ValueError(f"{phase}: unknown outcomes are not clear")


def _validate_phase06(report: dict[str, Any]) -> int:
    _validate_lineage(report, PHASE06_ID, "passed_with_gap")
    checks = report.get("checks")
    if not isinstance(checks, list) or not checks:
        raise ValueError("Phase 06 has no acceptance checks")
    ids: set[str] = set()
    for item in checks:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            raise ValueError("Phase 06 contains an invalid check")
        if item["id"] in ids or item.get("passed") is not True:
            raise ValueError(f"Phase 06 check is duplicate or failed: {item.get('id')!r}")
        if item.get("evidence") in (None, "", [], {}):
            raise ValueError(f"Phase 06 check has no evidence: {item['id']!r}")
        ids.add(item["id"])
    gaps = report.get("gaps")
    if not isinstance(gaps, list) or not gaps:
        raise ValueError("Phase 06 does not identify the gap it carried forward")
    if not all(_connector_fallback(gap) for gap in gaps):
        raise ValueError("Phase 06 contains a new or unrecognized local gap")
    return len(checks)


def _normalize_phase06_nodes(value: Any) -> tuple[Any, int]:
    if isinstance(value, list):
        rows, changes = [], 0
        for item in value:
            item, count = _normalize_phase06_nodes(item)
            rows.append(item)
            changes += count
        return rows, changes
    if not isinstance(value, dict):
        return value, 0

    result, changes = dict(value), 0
    identity = next(
        (result.get(k) for k in ("phase", "phase_id", "id") if isinstance(result.get(k), str)),
        None,
    )
    if identity == PHASE06_ID:
        for key in ("status", "verdict", "phase_status"):
            if result.get(key) == "passed_with_gap":
                result[key], changes = "passed", changes + 1
    for key, item in list(result.items()):
        if key == PHASE06_ID and item == "passed_with_gap":
            result[key], changes = "passed", changes + 1
            continue
        if key in {"phase06_status", "phase_06_status"} and item == "passed_with_gap":
            result[key], changes = "passed", changes + 1
            continue
        result[key], count = _normalize_phase06_nodes(item)
        changes += count
    return result, changes


def _required_artifacts(run_root: Path) -> dict[str, dict[str, Any]]:
    paths = {
        "export_bundle": run_root / "export/control-tower-retained.procesio",
        "ledger_csv": run_root / "export/evidence-ledger.csv",
        "deployment_manifest": run_root / "deployment.json",
        "final_report": run_root / "final-report.json",
    }
    result: dict[str, dict[str, Any]] = {}
    for name, path in paths.items():
        if not path.is_file() or path.stat().st_size <= 0:
            raise ValueError(f"required Phase 06 artifact is missing or empty: {path}")
        if path.suffix == ".json":
            _load(path, name)
        data = path.read_bytes()
        result[name] = {
            "path": str(path),
            "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        }
    return result


def _normalize_existing_phase06_report(run_root: Path) -> dict[str, Any] | None:
    phase06_path = run_root / f"phases/{PHASE06_ID}.json"
    if not phase06_path.is_file():
        return None
    phase06 = _load(phase06_path, "Phase 06 report")
    if phase06.get("status") != "passed_with_gap":
        return None

    check_count = _validate_phase06(phase06)
    phase03 = _load(run_root / f"phases/{PHASE03_ID}.json", "Phase 03 report")
    phase05 = _load(run_root / f"phases/{PHASE05_ID}.json", "Phase 05 report")
    _validate_lineage(phase03, PHASE03_ID, "passed_with_gap")
    _validate_lineage(phase05, PHASE05_ID, "passed")
    if not _connector_fallback({"summary": phase03.get("summary"), "gaps": phase03.get("gaps")}):
        raise ValueError("Phase 03 does not prove the approved connector fallback")
    artifacts = _required_artifacts(run_root)

    root = run_root / NORMALIZATION_RELATIVE
    phase_archive = root / "original-phase06-report.json"
    final_archive = root / "original-final-report.json"
    phase_bytes = _archive(phase06_path, phase_archive)
    _archive(run_root / "final-report.json", final_archive)
    normalized_at = datetime.now(timezone.utc).isoformat()

    original_gaps = phase06["gaps"]
    phase06["status"] = "passed"
    phase06["gaps"] = []
    phase06["inherited_project_gaps"] = original_gaps
    phase06["status_scope"] = {
        "phase_status": "passed",
        "aggregate_project_status": "passed_with_gap",
        "inherited_from_phase": PHASE03_ID,
        "normalized_at": normalized_at,
        "original_report": str(phase_archive),
        "original_report_sha256": hashlib.sha256(phase_bytes).hexdigest(),
    }

    final = _load(final_archive, "archived final report")
    final, changed = _normalize_phase06_nodes(final)
    assert isinstance(final, dict)
    record_path = root / "normalization.json"
    final["phase06_status_scope"] = {
        "phase_status": "passed",
        "aggregate_project_status": "passed_with_gap",
        "inherited_from_phase": PHASE03_ID,
        "normalization_record": str(record_path),
    }
    record = {
        "schema_version": 1,
        "kind": "procesio-control-tower-phase06-status-scope-normalization",
        "project_id": PROJECT_ID,
        "phase": PHASE06_ID,
        "normalized_at": normalized_at,
        "reason": "inherited_phase03_gap_was_misapplied_to_phase06_status",
        "phase_status_before": "passed_with_gap",
        "phase_status_after": "passed",
        "aggregate_project_status": "passed_with_gap",
        "inherited_from_phase": PHASE03_ID,
        "required_checks_passed": check_count,
        "final_report_phase_fields_changed": changed,
        "artifacts": artifacts,
        "platform_calls": 0,
        "model_calls": 0,
    }

    # Phase report is last: an interrupted repair remains rejected by the coordinator.
    _write(run_root / "final-report.json", final)
    _write(record_path, record)
    _write(phase06_path, phase06)
    return record


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.confirm != CONFIRMATION:
        print(json.dumps({"error": {"code": "confirmation_required", "message": f"Pass --confirm {CONFIRMATION}.", "details": {}}}, separators=(",", ":")))
        return 2
    if args.max_hours <= 0:
        print(json.dumps({"error": {"code": "invalid_configuration", "message": "--max-hours must be positive", "details": {}}}, separators=(",", ":")))
        return 2

    try:
        run_root = args.run_root.expanduser().resolve()
        module = _load_original()
        _install_execution_skill(module, args.skill_root.expanduser().resolve())
        normalized = _normalize_existing_phase06_report(run_root)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": {"code": "frozen_phase06_setup_failed", "message": str(exc), "details": {}}}, separators=(",", ":")))
        return 2

    if normalized:
        print(json.dumps({
            "schema_version": 1,
            "kind": "phase06_status_scope_normalized",
            "phase": PHASE06_ID,
            "status": "passed",
            "aggregate_project_status": "passed_with_gap",
            "normalization_record": str(run_root / NORMALIZATION_RELATIVE / "normalization.json"),
            "platform_calls": 0,
            "model_calls": 0,
        }, separators=(",", ":")))

    forwarded = [
        "--model", args.model,
        "--thinking", args.thinking,
        "--run-root", str(run_root),
        "--max-hours", str(args.max_hours),
        "--phase", PHASE06_ID,
        "--confirm", ORIGINAL_CONFIRMATION,
    ]
    if args.interactive_approval:
        forwarded.append("--interactive-approval")
    return int(module.main(forwarded))


if __name__ == "__main__":
    raise SystemExit(main())
