from __future__ import annotations

from types import SimpleNamespace

import pytest

import bridge
from tools._lib.skill_resources import SkillResourceError


def test_search_capabilities_returns_bounded_action_hits(monkeypatch):
    tools = [{
        "name": "procesio",
        "description": "PROCESIO platform API",
        "ready": True,
        "routing": None,
        "actions": [
            {"name": "create-schedule", "description": "Create a schedule for a process",
             "args": [{"name": "payload", "required": True}]},
            {"name": "list-processes", "description": "List processes", "args": []},
        ],
    }]
    monkeypatch.setattr(bridge, "_scan_registry", lambda: (tools, [], []))
    result = bridge.search_capabilities("create schedule", limit=1)
    assert result["count"] == 1
    assert result["total_matches"] >= 1
    assert result["results"][0]["action"] == "create-schedule"
    assert result["results"][0]["required_args"] == ["payload"]


def test_search_capabilities_can_find_skills(monkeypatch):
    skills = [{"name": "procesio-cli", "description": "Operate and troubleshoot PROCESIO",
               "ready": True, "routing": None}]
    monkeypatch.setattr(bridge, "_scan_registry", lambda: ([], [], skills))
    result = bridge.search_capabilities("troubleshoot PROCESIO", kind="skill")
    assert result["results"][0]["name"] == "procesio-cli"
    assert result["results"][0]["action"] is None


def test_capabilities_name_supports_skill_entries(monkeypatch):
    skills = [{"name": "demo", "description": "Demo skill", "ready": True,
               "routing": None}]
    monkeypatch.setattr(bridge, "_scan_registry", lambda: ([], [], skills))
    assert bridge.capabilities(name="demo")["capability"]["kind"] == "skill"


def test_get_skill_exposes_index_and_resource_read(monkeypatch, tmp_path):
    root = tmp_path / "demo"
    (root / "references").mkdir(parents=True)
    (root / "SKILL.md").write_text("---\nname: demo\ndescription: demo\n---\n# Demo\n")
    (root / "references" / "guide.md").write_text("guide", encoding="utf-8")
    monkeypatch.setattr(bridge.registry, "get_skill",
                        lambda name: SimpleNamespace(name=name, path=root))
    skill = bridge.get_skill("demo")
    assert skill["resources"]["references"] == ["references/guide.md"]
    resource = bridge.get_skill_resource("demo", "references/guide.md")
    assert resource["resource"]["content"] == "guide"
    with pytest.raises(SkillResourceError):
        bridge.get_skill_resource("demo", "../outside")
