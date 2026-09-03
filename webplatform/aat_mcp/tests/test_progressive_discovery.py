from __future__ import annotations

import json

import bridge
import server


def _payload(response):
    return json.loads(response["result"]["content"][0]["text"])


def _call(name, arguments):
    return server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                          "params": {"name": name, "arguments": arguments}})


def test_capabilities_query_routes_to_bounded_search(monkeypatch):
    monkeypatch.setattr(server.bridge, "search_capabilities",
                        lambda query, kind, name, limit: {"query": query, "count": limit})
    response = _call("capabilities", {"query": "schedule", "limit": 3})
    assert _payload(response) == {"query": "schedule", "count": 3}


def test_get_skill_without_resource_preserves_original_operation(monkeypatch):
    monkeypatch.setattr(server.bridge, "get_skill",
                        lambda name: {"name": name, "content": "# Skill", "resources": {}})
    response = _call("get_skill", {"name": "demo"})
    assert _payload(response)["content"] == "# Skill"


def test_get_skill_resource_uses_index_path(monkeypatch):
    monkeypatch.setattr(server.bridge, "get_skill_resource",
                        lambda name, path: {"name": name, "resource": {"path": path}})
    response = _call("get_skill", {"name": "demo", "resource": "references/guide.md"})
    assert _payload(response)["resource"]["path"] == "references/guide.md"


def test_get_skill_resource_failure_is_structured(monkeypatch):
    def fail(name, path):
        raise ValueError("resource path must stay inside the skill")
    monkeypatch.setattr(server.bridge, "get_skill_resource", fail)
    response = _call("get_skill", {"name": "demo", "resource": "../secret"})
    assert response["result"]["isError"] is True
    assert "stay inside" in _payload(response)["error"]
