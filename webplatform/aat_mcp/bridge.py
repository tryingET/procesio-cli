"""AAT-facing logic for the MCP bridge — pure, testable, no protocol code.

Exposes the live registry to a driver as a small generic surface and executes
capabilities by shelling to scripts/run-tool.py / run-agent.py with a Python LIST
argv (no shell), so structured args (including JSON objects) pass cleanly. It also
supports bounded capability search and progressive skill-resource retrieval.
"""
from __future__ import annotations

import contextvars
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import registry  # noqa: E402
from dashboard.server import runner  # noqa: E402
from tools._lib import accounting  # noqa: E402
from tools._lib.skill_resources import read_text_resource, resource_index  # noqa: E402

_user_ctx: "contextvars.ContextVar" = contextvars.ContextVar("aat_user_id", default=None)


def set_user(uid: str | None):
    """Set the current request's user; returns a token for reset_user()."""
    return _user_ctx.set(uid or None)


def reset_user(token) -> None:
    _user_ctx.reset(token)


_workspace_ctx: "contextvars.ContextVar" = contextvars.ContextVar(
    "aat_workspace_id", default=None)


def set_workspace(ws: str | None):
    """Set the current request's workspace; returns a token for reset_workspace()."""
    return _workspace_ctx.set(ws or None)


def reset_workspace(token) -> None:
    _workspace_ctx.reset(token)


def _user_env() -> dict | None:
    env: dict = {}
    uid = _user_ctx.get()
    if uid:
        env["AAT_USER_ID"] = str(uid)
    ws = _workspace_ctx.get()
    if ws:
        env["AAT_WORKSPACE_ID"] = str(ws)
    return env or None


_HOST_ONLY_TOOLS = {
    "sqlserver", "web",
}


def _host_only_set() -> set[str]:
    extra = {t.strip() for t in os.environ.get("AAT_HOST_ONLY_TOOLS", "").split(",") if t.strip()}
    return _HOST_ONLY_TOOLS | extra


def _is_host_only(kind: str, name: str) -> bool:
    """A tool is host-only if listed or declares a web session; agents inherit it."""
    host_set = _host_only_set()
    if kind == "tool":
        if name in host_set:
            return True
        try:
            return getattr(registry.get_tool(name), "web_session", None) is not None
        except Exception:  # noqa: BLE001
            return False
    try:
        drives = set(getattr(registry.get_agent(name), "tools", []) or [])
    except Exception:  # noqa: BLE001
        return False
    if drives & host_set:
        return True
    for tool in drives:
        try:
            if getattr(registry.get_tool(tool), "web_session", None) is not None:
                return True
        except Exception:  # noqa: BLE001
            pass
    return False


def _delegate(kind: str, name: str, action: str | None, args: dict | None) -> dict:
    """Run a host-only tool/agent on the host via the host-runner."""
    url = os.environ["AAT_HOST_RUNNER_URL"].rstrip("/") + "/run"
    token = os.environ.get("AAT_HOST_RUNNER_TOKEN", "")
    payload = json.dumps({"kind": kind, "name": name, "action": action,
                          "args": args or {}}).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    uid = _user_ctx.get()
    if uid:
        headers["X-AAT-User"] = str(uid)
    ws = _workspace_ctx.get()
    if ws:
        headers["X-AAT-Workspace"] = str(ws)
    req = urllib.request.Request(url, data=payload, method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=330) as resp:  # noqa: S310 (host-local)
            return json.loads(resp.read().decode("utf-8") or "null")
    except urllib.error.URLError as exc:
        return {"ok": False, "error": {"code": "host_runner_unreachable",
                                       "message": f"host-only {kind} {name!r}: {exc}"}}


def _compact(entry: dict, kind: str) -> dict:
    routing = entry.get("routing") or {}
    return {
        "kind": kind,
        "name": entry["name"],
        "description": (entry.get("description") or "")[:240],
        "primary_action": routing.get("primary_action", ""),
        "example": routing.get("example", ""),
        "ready": bool(entry.get("ready", True)),
    }


def _full(entry: dict, kind: str) -> dict:
    """Full action + arg schema for one capability."""
    def _args(arglist):
        return [
            {
                "name": arg["name"],
                "type": arg.get("type", "string"),
                "required": bool(arg.get("required", False)),
                "description": arg.get("description", ""),
            }
            for arg in (arglist or [])
        ]

    return {
        "kind": kind,
        "name": entry["name"],
        "description": entry.get("description", ""),
        "ready": bool(entry.get("ready", True)),
        "missing_secrets": entry.get("missing_secrets", []),
        "tools": entry.get("tools", []) if kind == "agent" else None,
        "args": _args(entry.get("args")) if not entry.get("actions") else [],
        "actions": [
            {
                "name": action["name"],
                "description": action.get("description", ""),
                "args": [
                    {
                        "name": arg["name"],
                        "type": arg.get("type", "string"),
                        "required": bool(arg.get("required", False)),
                        "description": arg.get("description", ""),
                    }
                    for arg in action.get("args", [])
                ],
            }
            for action in entry.get("actions", [])
        ],
    }


_REG_CACHE: dict = {}


def _scan_registry():
    """Cache registry scans for AAT_REGISTRY_TTL seconds (0 disables caching)."""
    ttl = float(os.environ.get("AAT_REGISTRY_TTL", "30") or 0)
    if ttl > 0:
        hit = _REG_CACHE.get("data")
        if hit is not None and hit[1] > time.monotonic():
            return hit[0]
    tools = registry.list_tools()
    agents = registry.list_agents({tool["name"]: tool for tool in tools})
    skills = registry.list_skills()
    if ttl > 0:
        _REG_CACHE["data"] = ((tools, agents, skills), time.monotonic() + ttl)
    return tools, agents, skills


def capabilities(kind: str | None = None, name: str | None = None) -> dict:
    """List compact capabilities or return one full tool/agent/skill entry."""
    tools, agents, skills = _scan_registry()

    if name:
        for entry_kind, entries in (("tool", tools), ("agent", agents), ("skill", skills)):
            for entry in entries:
                if entry.get("name") == name:
                    return {"capability": _full(entry, entry_kind)}
        raise KeyError(f"no tool, agent, or skill named {name!r}")

    out: list[dict] = []
    if kind in (None, "tool"):
        out += [_compact(entry, "tool") for entry in tools if not entry.get("error")]
    if kind in (None, "agent"):
        out += [_compact(entry, "agent") for entry in agents if not entry.get("error")]
    if kind in (None, "skill"):
        out += [_compact(entry, "skill") for entry in skills if not entry.get("error")]
    return {"count": len(out), "capabilities": out}


_SEARCH_TOKEN = re.compile(r"[a-z0-9][a-z0-9._+-]*", re.IGNORECASE)


def _search_tokens(value: str) -> list[str]:
    return [token.lower() for token in _SEARCH_TOKEN.findall(value or "")]


def _search_score(query: str, text: str) -> int:
    query_norm = " ".join(_search_tokens(query))
    text_norm = " ".join(_search_tokens(text))
    if not query_norm or not text_norm:
        return 0
    score = 25 if query_norm in text_norm else 0
    for token in set(query_norm.split()):
        if token in text_norm.split():
            score += 4
        elif token in text_norm:
            score += 1
    return score


def search_capabilities(query: str, kind: str | None = None,
                        name: str | None = None, limit: int = 10) -> dict:
    """Search capability and action metadata without returning the whole registry."""
    query = str(query or "").strip()
    if not query:
        raise ValueError("query is required")
    if kind not in (None, "tool", "agent", "skill"):
        raise ValueError("kind must be tool, agent, or skill")
    limit = max(1, min(int(limit or 10), 50))
    tools, agents, skills = _scan_registry()
    results: list[dict[str, Any]] = []

    for entry_kind, entries in (("tool", tools), ("agent", agents), ("skill", skills)):
        if kind and entry_kind != kind:
            continue
        for entry in entries:
            if entry.get("error") or (name and entry.get("name") != name):
                continue
            routing = entry.get("routing") or {}
            base_text = " ".join([
                entry.get("name", ""), entry.get("description", ""),
                " ".join(routing.get("triggers") or []),
            ])
            base_score = _search_score(query, base_text)
            if base_score:
                results.append({
                    "kind": entry_kind,
                    "name": entry["name"],
                    "action": None,
                    "description": (entry.get("description") or "")[:320],
                    "score": base_score,
                    "ready": bool(entry.get("ready", True)),
                })
            if entry_kind == "skill":
                continue
            for action in entry.get("actions") or []:
                args = action.get("args") or []
                action_text = " ".join([
                    entry.get("name", ""), action.get("name", ""),
                    action.get("description", ""),
                    " ".join(arg.get("name", "") for arg in args),
                ])
                action_score = _search_score(query, action_text)
                if not action_score:
                    continue
                results.append({
                    "kind": entry_kind,
                    "name": entry["name"],
                    "action": action["name"],
                    "description": (action.get("description") or "")[:320],
                    "required_args": [arg["name"] for arg in args if arg.get("required")],
                    "score": action_score + 2,
                    "ready": bool(entry.get("ready", True)),
                })

    results.sort(key=lambda row: (-row["score"], row["kind"], row["name"], row.get("action") or ""))
    total = len(results)
    return {"query": query, "total_matches": total, "count": min(total, limit),
            "results": results[:limit]}


def run_tool(tool: str, action: str | None, args: dict[str, Any] | None) -> dict:
    """Execute a tool with structured arguments."""
    with accounting.work_unit("tool", ws=_workspace_ctx.get(),
                              user=_user_ctx.get()) as work_unit:
        work_unit["tool"] = tool
        if action:
            work_unit["action"] = action
        if os.environ.get("AAT_HOST_RUNNER_URL") and _is_host_only("tool", tool):
            return _delegate("tool", tool, action, args)
        argv = ([action] if action else []) + runner.flags_from(args)
        return runner.run_tool(tool, argv, env=_user_env())


def run_agent(agent: str, action: str | None, args: dict[str, Any] | None) -> dict:
    with accounting.work_unit("agent", ws=_workspace_ctx.get(),
                              user=_user_ctx.get()) as work_unit:
        work_unit["agent"] = agent
        if action:
            work_unit["action"] = action
        if os.environ.get("AAT_HOST_RUNNER_URL") and _is_host_only("agent", agent):
            return _delegate("agent", agent, action, args)
        argv = ([action] if action else []) + runner.flags_from(args)
        return runner.run_agent(agent, argv, env=_user_env())


def get_skill(name: str) -> dict:
    """Return a skill's markdown plus a metadata-only bundled-resource index."""
    manifest = registry.get_skill(name)
    markdown = (manifest.path / "SKILL.md").read_text(encoding="utf-8")
    return {"name": manifest.name, "content": markdown,
            "resources": resource_index(manifest.path)}


def get_skill_resource(name: str, path: str) -> dict:
    """Return one safe UTF-8 resource below references/, scripts/, or assets/."""
    manifest = registry.get_skill(name)
    return {"name": manifest.name, "resource": read_text_resource(manifest.path, path)}
