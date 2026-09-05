#!/usr/bin/env -S uv run --script
#
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Canonical entry point for Control Tower Phase 05 remediation and completion.

Before importing the staged remediation coordinator, this wrapper snapshots the
entire ``procesio-cli`` skill package into the gitignored run root and verifies a
content fingerprint on every resume. The acting agent therefore sees one frozen
skill corpus, not whichever references happen to be on a later checkout.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SOURCE_SKILL = ROOT / "skills" / "procesio-cli"
INNER = ROOT / "scripts" / "run-procesio-control-tower-phase05-remediation.py"
DEFAULT_RUN_ROOT = ROOT / "scratchpad" / "procesio-control-tower-v1"
SNAPSHOT_RELATIVE = Path("remediation") / "phase05" / "frozen-skill" / "procesio-cli"
MANIFEST_NAME = "skill-snapshot.json"


def _run_root(argv: list[str]) -> Path:
    for index, arg in enumerate(argv):
        if arg == "--run-root":
            if index + 1 >= len(argv):
                raise ValueError("--run-root requires a path")
            return Path(argv[index + 1]).expanduser().resolve()
        if arg.startswith("--run-root="):
            return Path(arg.split("=", 1)[1]).expanduser().resolve()
    return DEFAULT_RUN_ROOT.resolve()


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


def _load_inner():
    spec = importlib.util.spec_from_file_location(
        "run_procesio_control_tower_phase05_remediation", INNER
    )
    if spec is None or spec.loader is None:
        raise ValueError(f"cannot import remediation coordinator: {INNER}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        run_root = _run_root(args)
        snapshot = _snapshot(run_root)
        module = _load_inner()
        module.SKILL = snapshot
        return int(module.main(args))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(
            json.dumps(
                {
                    "error": {
                        "code": "skill_snapshot_error",
                        "message": str(exc),
                        "details": {"automatic_rebuild": False},
                    }
                },
                separators=(",", ":"),
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
