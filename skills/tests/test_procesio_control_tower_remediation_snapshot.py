from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "run-procesio-control-tower-remediation.py"


def _load():
    spec = importlib.util.spec_from_file_location(
        "run_procesio_control_tower_remediation", SCRIPT
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _source(tmp_path: Path) -> Path:
    root = tmp_path / "source-skill"
    (root / "references").mkdir(parents=True)
    (root / "SKILL.md").write_text("---\nname: test\n---\n# Test\n", encoding="utf-8")
    (root / "references" / "one.md").write_text("one\n", encoding="utf-8")
    return root


def test_wrapper_is_uv_inline_script():
    text = SCRIPT.read_text(encoding="utf-8")
    assert text.startswith("#!/usr/bin/env -S uv run --script")
    assert '# requires-python = ">=3.11"' in text
    assert "module.SKILL = snapshot" in text


def test_run_root_parsing():
    module = _load()
    assert module._run_root(["--run-root", "abc"]).name == "abc"
    assert module._run_root(["--run-root=def"]).name == "def"
    with pytest.raises(ValueError, match="requires a path"):
        module._run_root(["--run-root"])


def test_snapshot_copies_and_freezes_entire_skill_package(tmp_path, monkeypatch):
    module = _load()
    source = _source(tmp_path)
    monkeypatch.setattr(module, "SOURCE_SKILL", source)
    run_root = tmp_path / "run"

    snapshot = module._snapshot(run_root)
    manifest_path = snapshot.parent / module.MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert snapshot != source
    assert (snapshot / "SKILL.md").is_file()
    assert (snapshot / "references" / "one.md").read_text() == "one\n"
    assert manifest["file_count"] == 2
    assert manifest["fingerprint_sha256"] == module._tree_fingerprint(snapshot)[0]

    # Later source edits do not contaminate the frozen field run.
    (source / "references" / "one.md").write_text("changed upstream\n", encoding="utf-8")
    assert module._snapshot(run_root) == snapshot
    assert (snapshot / "references" / "one.md").read_text() == "one\n"


def test_snapshot_fails_closed_on_tamper_or_partial_state(tmp_path, monkeypatch):
    module = _load()
    source = _source(tmp_path)
    monkeypatch.setattr(module, "SOURCE_SKILL", source)
    run_root = tmp_path / "run"
    snapshot = module._snapshot(run_root)

    (snapshot / "references" / "one.md").write_text("tampered\n", encoding="utf-8")
    with pytest.raises(ValueError, match="frozen skill package changed"):
        module._snapshot(run_root)

    other = tmp_path / "other"
    partial = other / module.SNAPSHOT_RELATIVE
    partial.mkdir(parents=True)
    with pytest.raises(ValueError, match="partial skill snapshot"):
        module._snapshot(other)
