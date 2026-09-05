#!/usr/bin/env -S uv run --script
#
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Canonical entry point for Control Tower Phase 05 remediation and completion.

Before importing the staged remediation coordinator, this wrapper snapshots the
entire ``procesio-cli`` skill package into the gitignored run root and verifies a
content fingerprint on every resume. The acting agents therefore see one frozen
skill corpus through remediation and the final Phase 06 audit/export.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SOURCE_SKILL = ROOT / "skills" / "procesio-cli"
INNER = ROOT / "scripts" / "run-procesio-control-tower-phase05-remediation.py"
PHASE6 = ROOT / "scripts" / "run-procesio-control-tower-phase06-frozen.py"
DEFAULT_RUN_ROOT = ROOT / "scratchpad" / "procesio-control-tower-v1"
SNAPSHOT_RELATIVE = Path("remediation") / "phase05" / "frozen-skill" / "procesio-cli"
MANIFEST_NAME = "skill-snapshot.json"
PHASE6_CONFIRMATION = "FINISH_PROCESIO_CONTROL_TOWER_V1_PHASE06"


def _run_root(argv: list[str]) -> Path:
    for index, arg in enumerate(argv):
        if arg == "--run-root":
            if index + 1 >= len(argv):
                raise ValueError("--run-root requires a path")
            return Path(argv[index + 1]).expanduser().resolve()
        if arg.startswith("--run-root="):
            return Path(arg.split("=", 1)[1]).expanduser().resolve()
    return DEFAULT_RUN_ROOT.resolve()


def _arg_value(argv: list[str], name: str, default: str) -> str:
    for index, arg in enumerate(argv):
        if arg == name:
            if index + 1 >= len(argv):
                raise ValueError(f"{name} requires a value")
            return argv[index + 1]
        if arg.startswith(name + "="):
            return arg.split("=", 1)[1]
    return default


def _files(root: Path) -> list[Path]:
    return sorted(
        path
        for path in root.rglob("*")
        if path.is_file()
        and "__pycache__" not in path.parts
        and path.suffix not in {".pyc", ".pyo"}
    )


def _tree_fingerprint(root: Path) -> tuple[str, list[dict[str, Any]]]:
    digest = hashlib.sha256()
    records: list[dict[str, Any]] = []
    for path in _files(root):
        relative = path.relative_to(root).as_posix()
        content = path.read_bytes()
        file_hash = hashlib.sha256(content).hexdigest()
        encoded = relative.encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
        records.append({"path": relative, "bytes": len(content), "sha256": file_hash})
    return digest.hexdigest(), records


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _source_label() -> str:
    try:
        return str(SOURCE_SKILL.relative_to(ROOT))
    except ValueError:
        return str(SOURCE_SKILL)


def _snapshot(run_root: Path) -> Path:
    snapshot = run_root / SNAPSHOT_RELATIVE
    manifest_path = snapshot.parent / MANIFEST_NAME
    if snapshot.exists() != manifest_path.exists():
        raise ValueError(
            "partial skill snapshot exists; inspect it instead of deleting or rebuilding evidence"
        )

    if not snapshot.exists():
        if not (SOURCE_SKILL / "SKILL.md").is_file():
            raise ValueError(f"source skill is missing: {SOURCE_SKILL}")
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        temporary = snapshot.with_name(snapshot.name + ".tmp")
        if temporary.exists():
            shutil.rmtree(temporary)
        shutil.copytree(SOURCE_SKILL, temporary)
        temporary.replace(snapshot)
        fingerprint, files = _tree_fingerprint(snapshot)
        _write_json(
            manifest_path,
            {
                "schema_version": 1,
                "kind": "frozen-agent-skill-package",
                "source": _source_label(),
                "snapshot": str(snapshot),
                "fingerprint_sha256": fingerprint,
                "file_count": len(files),
                "files": files,
            },
        )
        return snapshot

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        raise ValueError("skill snapshot manifest is invalid")
    fingerprint, files = _tree_fingerprint(snapshot)
    if fingerprint != manifest.get("fingerprint_sha256"):
        raise ValueError(
            "frozen skill package changed since the remediation began; restore the snapshot "
            "or use a new reviewed run root"
        )
    if len(files) != manifest.get("file_count"):
        raise ValueError("frozen skill package file count changed")
    return snapshot


def _load(path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ValueError(f"cannot import coordinator: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_inner():
    return _load(INNER, "run_procesio_control_tower_phase05_remediation")


def _load_phase6():
    return _load(PHASE6, "run_procesio_control_tower_phase06_frozen")


def _emit_error(code: str, message: str) -> int:
    print(
        json.dumps(
            {
                "error": {
                    "code": code,
                    "message": message,
                    "details": {"automatic_rebuild": False},
                }
            },
            separators=(",", ":"),
        )
    )
    return 2


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    started = time.monotonic()
    try:
        run_root = _run_root(args)
        snapshot = _snapshot(run_root)
        inner = _load_inner()
        inner.SKILL = snapshot

        # Dry-run is already non-mutating and should show the original coordinator's
        # complete plan. An explicit --no-phase6 remains an intentional stop point.
        if "--dry-run" in args or "--no-phase6" in args:
            return int(inner.main(args))

        max_hours = float(_arg_value(args, "--max-hours", "8"))
        model = _arg_value(
            args,
            "--model",
            os.environ.get("PI_CONTROL_TOWER_MODEL", inner.DEFAULT_MODEL),
        )
        thinking = _arg_value(
            args,
            "--thinking",
            os.environ.get("PI_CONTROL_TOWER_THINKING", inner.DEFAULT_THINKING),
        )
        interactive = "--interactive-approval" in args

        # Let the remediation coordinator repair and promote Phase 05, but prevent
        # its legacy live-checkout Phase 06 path. The frozen helper owns Phase 06.
        remediation_args = [*args, "--no-phase6"]
        code = int(inner.main(remediation_args))
        if code != 0:
            return code

        remaining_hours = max_hours - (time.monotonic() - started) / 3600
        if remaining_hours <= 1 / 60:
            print(
                json.dumps(
                    {
                        "schema_version": 1,
                        "state": "paused",
                        "reason": "Phase 05 is repaired, but less than one minute remains for Phase 06.",
                        "run_root": str(run_root),
                        "frozen_skill_root": str(snapshot),
                    },
                    separators=(",", ":"),
                )
            )
            return 75

        phase6 = _load_phase6()
        forwarded = [
            "--model",
            model,
            "--thinking",
            thinking,
            "--run-root",
            str(run_root),
            "--skill-root",
            str(snapshot),
            "--max-hours",
            str(remaining_hours),
            "--confirm",
            PHASE6_CONFIRMATION,
        ]
        if interactive:
            forwarded.append("--interactive-approval")
        return int(phase6.main(forwarded))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return _emit_error("skill_snapshot_or_coordination_error", str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
