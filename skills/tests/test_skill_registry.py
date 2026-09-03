from __future__ import annotations

import json
from pathlib import Path

import pytest

import registry


def _write_skill(root: Path, name: str, body: str = "# Demo\n") -> Path:
    skill_root = root / name
    (skill_root / "evals").mkdir(parents=True)
    (skill_root / "evals" / "evals.json").write_text(
        json.dumps({"skill_name": name, "evals": []}), encoding="utf-8"
    )
    skill_md = skill_root / "SKILL.md"
    skill_md.write_text(
        "---\n"
        f"name: {name}\n"
        "description: Use when testing registry skill behavior.\n"
        "version: 1.0.0\n"
        "tier: template\n"
        "owner: test-owner\n"
        "last_verified: 2026-09-03\n"
        "baseline_version: abc123\n"
        "eval_suite: evals/evals.json\n"
        "source_policy: static\n"
        "routing:\n"
        "  triggers: [test registry skills]\n"
        "  primary_action: test\n"
        "---\n\n"
        f"{body}",
        encoding="utf-8",
    )
    return skill_md


def test_registry_exposes_governance_metadata(monkeypatch, tmp_path):
    _write_skill(tmp_path, "demo")
    monkeypatch.setattr(registry, "SKILLS_DIR", tmp_path)
    entries = registry.list_skills()
    assert entries == [{
        "name": "demo",
        "description": "Use when testing registry skill behavior.",
        "version": "1.0.0",
        "tier": "template",
        "path": str(tmp_path / "demo"),
        "routing": {"triggers": ["test registry skills"],
                    "primary_action": "test", "example": ""},
        "owner": "test-owner",
        "last_verified": "2026-09-03",
        "baseline_version": "abc123",
        "eval_suite": "evals/evals.json",
        "source_policy": "static",
        "readiness": "ready",
        "ready": True,
    }]


def test_registry_refuses_skill_with_broken_resource(monkeypatch, tmp_path):
    skill_md = _write_skill(tmp_path, "broken", "Read `references/missing.md`.\n")
    (skill_md.parent / "references").mkdir()
    monkeypatch.setattr(registry, "SKILLS_DIR", tmp_path)
    entry = registry.list_skills()[0]
    assert entry["ready"] is False
    assert entry["readiness"] == "invalid"
    assert "resource does not exist" in entry["error"]
    with pytest.raises(ValueError, match="invalid"):
        registry.get_skill("broken")
