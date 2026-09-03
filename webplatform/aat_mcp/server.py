"""aat-mcp: a stdio MCP server exposing the AAT registry as a small generic surface.

The server keeps execution generic while supporting progressive discovery:

  capabilities         - list capabilities, inspect one schema, or search metadata
  run_tool             - run a REVERSIBLE tool with structured JSON args
  run_agent            - run a REVERSIBLE agent
  run_tool_confirmed   - run a tool INCLUDING irreversible actions
  run_agent_confirmed  - run an agent INCLUDING irreversible actions
  get_skill            - fetch SKILL.md/index, or one safe bundled resource

Safety: irreversible execution is code-gated before dispatch. Skill-resource
retrieval is path-confined by tools._lib.skill_resources.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bridge  # noqa: E402
import gate  # noqa: E402

SERVER_INFO = {"name": "aat-mcp", "version": "0.3.0"}
DEFAULT_PROTOCOL = "2024-11-05"

_RUN_TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "tool": {"type": "string", "description": "registered tool name"},
        "action": {"type": "string", "description": "action name (omit for a flat tool)"},
        "args": {"type": "object", "description": "flag name -> value (objects/arrays pass cleanly)"},
    },
    "required": ["tool"],
}
_RUN_AGENT_SCHEMA = {
    "type": "object",
    "properties": {
        "agent": {"type": "string", "description": "registered agent name"},
        "action": {"type": "string", "description": "action name"},
        "args": {"type": "object", "description": "flag name -> value"},
    },
    "required": ["agent"],
}

TOOLS = [
    {
        "name": "capabilities",
        "description": (
            "List AAT capabilities. No args returns a compact list. Pass name to "
            "get one tool, agent, or skill's full schema. Pass query for bounded "
            "search across capability, action, and argument metadata."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": ["tool", "agent", "skill"]},
                "name": {"type": "string"},
                "query": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10},
            },
        },
    },
    {
        "name": "run_tool",
        "description": (
            "Run a registered AAT tool for a REVERSIBLE/read action with structured "
            "JSON args. Irreversible actions return approval_required."
        ),
        "inputSchema": _RUN_TOOL_SCHEMA,
    },
    {
        "name": "run_tool_confirmed",
        "description": "Run a tool INCLUDING an operator-approved irreversible action.",
        "inputSchema": _RUN_TOOL_SCHEMA,
    },
    {
        "name": "run_agent",
        "description": (
            "Run a registered AAT agent for a REVERSIBLE action. Irreversible agent "
            "actions are refused here; use run_agent_confirmed."
        ),
        "inputSchema": _RUN_AGENT_SCHEMA,
    },
    {
        "name": "run_agent_confirmed",
        "description": "Run an agent INCLUDING an operator-approved irreversible action.",
        "inputSchema": _RUN_AGENT_SCHEMA,
    },
    {
        "name": "get_skill",
        "description": (
            "Fetch a registered skill's SKILL.md plus resource index. To retrieve one "
            "resource, pass a path returned by that index in the optional resource field."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "resource": {"type": "string"},
            },
            "required": ["name"],
        },
    },
]


def _log(msg: str) -> None:
    print(f"[aat-mcp] {msg}", file=sys.stderr, flush=True)


def _run(kind: str, arguments: dict, confirmed: bool) -> tuple[dict, bool]:
    """Execute a tool/agent through the reversibility gate."""
    key = "tool" if kind == "tool" else "agent"
    target = arguments.get(key)
    if not target:
        return {"error": f"run_{kind} requires '{key}'"}, True
    action = arguments.get("action")
    verdict = gate.classify(target, action)

    if not confirmed and not verdict["reversible"]:
        return {"approval_required": {
            key: target, "action": action, "verb": verdict["verb"],
            "blast_class": verdict["blast_class"], "reason": verdict["reason"],
            "next": (f"This action is irreversible ({verdict['blast_class']}). To "
                     f"proceed, call run_{kind}_confirmed with the same arguments - "
                     f"the operator will be asked to approve it."),
        }}, False

    if confirmed and not verdict["reversible"] and gate.deny_irreversible_env():
        return {"refused": ("irreversible action denied (AAT_MCP_DENY_IRREVERSIBLE "
                            "is set; no human in the seat)"),
                "verb": verdict["verb"], "blast_class": verdict["blast_class"]}, True

    runner = bridge.run_tool if kind == "tool" else bridge.run_agent
    result = runner(target, action, arguments.get("args"))
    if not result.get("ok", False):
        result = dict(result)
        result["hint"] = (f"This {kind} call failed - it does NOT mean you lack access. "
                          f"Call capabilities with name='{target}' to inspect valid "
                          f"actions and required args, then retry run_{kind}.")
        return result, True
    return result, False


def _call_tool(name: str, arguments: dict) -> tuple[dict, bool]:
    """Return (payload, is_error); never leak an exception through JSON-RPC."""
    try:
        if name == "capabilities":
            if arguments.get("query"):
                return bridge.search_capabilities(
                    arguments["query"], arguments.get("kind"), arguments.get("name"),
                    arguments.get("limit", 10)
                ), False
            return bridge.capabilities(arguments.get("kind"), arguments.get("name")), False
        if name == "run_tool":
            return _run("tool", arguments, confirmed=False)
        if name == "run_tool_confirmed":
            return _run("tool", arguments, confirmed=True)
        if name == "run_agent":
            return _run("agent", arguments, confirmed=False)
        if name == "run_agent_confirmed":
            return _run("agent", arguments, confirmed=True)
        if name == "get_skill":
            if not arguments.get("name"):
                return {"error": "get_skill requires 'name'"}, True
            if arguments.get("resource"):
                return bridge.get_skill_resource(arguments["name"], arguments["resource"]), False
            return bridge.get_skill(arguments["name"]), False
        return {"error": f"unknown tool: {name}"}, True
    except KeyError as exc:
        return {"error": str(exc)}, True
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}, True


def handle(req: dict) -> dict | None:
    """Dispatch one JSON-RPC request; notifications return None."""
    method = req.get("method")
    req_id = req.get("id")
    is_notification = "id" not in req

    def ok(result):
        return {"jsonrpc": "2.0", "id": req_id, "result": result}

    def err(code, message):
        return {"jsonrpc": "2.0", "id": req_id,
                "error": {"code": code, "message": message}}

    if method == "initialize":
        params = req.get("params") or {}
        protocol = params.get("protocolVersion") or DEFAULT_PROTOCOL
        return ok({"protocolVersion": protocol,
                   "capabilities": {"tools": {"listChanged": False}},
                   "serverInfo": SERVER_INFO})
    if method == "notifications/initialized" or (method or "").startswith("notifications/"):
        return None
    if method == "ping":
        return ok({})
    if method == "tools/list":
        return ok({"tools": TOOLS})
    if method == "tools/call":
        params = req.get("params") or {}
        tool_name = params.get("name", "")
        arguments = params.get("arguments") or {}
        payload, is_error = _call_tool(tool_name, arguments)
        text = json.dumps(payload, ensure_ascii=False)
        return ok({"content": [{"type": "text", "text": text}], "isError": is_error})

    if is_notification:
        return None
    return err(-32601, f"method not found: {method}")


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", newline="\n")
        sys.stdin.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    _log("started (stdio). Waiting for JSON-RPC on stdin.")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except ValueError:
            sys.stdout.write(json.dumps(
                {"jsonrpc": "2.0", "id": None,
                 "error": {"code": -32700, "message": "parse error"}}) + "\n")
            sys.stdout.flush()
            continue
        try:
            response = handle(request)
        except Exception as exc:  # noqa: BLE001
            _log(f"handler error: {exc}")
            response = {"jsonrpc": "2.0", "id": request.get("id"),
                        "error": {"code": -32603, "message": f"internal error: {exc}"}}
        if response is not None:
            sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
