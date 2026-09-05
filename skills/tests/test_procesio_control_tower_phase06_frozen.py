from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "run-procesio-control-tower-phase06-frozen.py"


def _load():
    spec = importlib.util.spec_from_file_location(
        "run_procesio_control_tower_phase06_frozen", SCRIPT
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _skill(path: Path) -> Path:
    path.mkdir(parents=True)
    (path / "SKILL.md").write_text("---\nname: procesio-cli\n---\n", encoding="utf-8")
    return path


def test_helper_is_uv_script_and_requires_separate_confirmation(capsys):
    text = SCRIPT.read_text(encoding="utf-8")
    assert text.startswith("#!/usr/bin/env -S uv run --script")
    assert '# requires-python = ">=3.11"' in text
    module = _load()

    code = module.main(
        [
            "--model",
            "zai/glm-5.3",
            "--thinking",
            "high",
            "--max-hours",
            "1",
        ]
    )
    assert code == 2
    result = json.loads(capsys.readouterr().out)
    assert result["error"]["code"] == "confirmation_required"
    assert module.CONFIRMATION in result["error"]["message"]


def test_install_execution_skill_preserves_original_metadata_identity(tmp_path):
    helper = _load()
    original = _skill(tmp_path / "original")
    frozen = _skill(tmp_path / "frozen")
    contract = tmp_path / "contract"
    manifest = tmp_path / "manifest"
    seeds = tmp_path / "seeds"
    openapi = tmp_path / "openapi"
    for path in (contract, manifest, seeds, openapi):
        path.write_text("x", encoding="utf-8")

    module = SimpleNamespace(
        SKILL=original,
        CONTRACT=contract,
        MANIFEST=manifest,
        SEEDS=seeds,
        OPENAPI=openapi,
    )
    module._metadata_value = lambda model, thinking: {
        "model": model,
        "thinking": thinking,
        "skill": str(module.SKILL),
    }
    module._required_files = lambda: ()

    helper._install_execution_skill(module, frozen)

    assert module.SKILL == frozen
    assert module._metadata_value("zai/glm-5.3", "high")["skill"] == str(original)
    assert module.SKILL == frozen  # metadata call restored the execution root
    required = module._required_files()
    assert original / "SKILL.md" in required
    assert frozen / "SKILL.md" in required


def test_main_forwards_only_phase06_with_frozen_skill(tmp_path, monkeypatch):
    helper = _load()
    original = _skill(tmp_path / "original")
    frozen = _skill(tmp_path / "frozen")
    calls: list[str] = []

    module = SimpleNamespace(
        SKILL=original,
        CONTRACT=tmp_path / "contract",
        MANIFEST=tmp_path / "manifest",
        SEEDS=tmp_path / "seeds",
        OPENAPI=tmp_path / "openapi",
    )
    module._metadata_value = lambda model, thinking: {"skill": str(module.SKILL)}
    module._required_files = lambda: ()
    module.main = lambda argv: calls.extend(argv) or 0
    monkeypatch.setattr(helper, "_load_original", lambda: module)

    code = helper.main(
        [
            "--model",
            "zai/glm-5.3",
            "--thinking",
            "high",
            "--run-root",
            str(tmp_path / "run"),
            "--skill-root",
            str(frozen),
            "--max-hours",
            "1",
            "--confirm",
            helper.CONFIRMATION,
        ]
    )

    assert code == 0
    assert module.SKILL == frozen
    assert calls[calls.index("--phase") + 1] == helper.PHASE06_ID
    assert calls[calls.index("--confirm") + 1] == helper.ORIGINAL_CONFIRMATION
    assert calls[calls.index("--model") + 1] == "zai/glm-5.3"
    assert calls[calls.index("--thinking") + 1] == "high"
