"""Auth lifecycle actions: login, check-auth, logout.

These are client-backed (they need a profile + session) but deliberately never
return a token value - only whether authentication works and how it was done.
"""
from __future__ import annotations

from tools.procesio import auth, config, profiles
from tools.procesio.actiondef import ActionDef
from tools.procesio.errors import ProcesioAPIError
from tools.procesio.handlers.common import add_profile_arg

_ACCOUNT_PROBE_PATH = "/api/Workspaces"
_WORKSPACE_PROBE_PATH = "/api/Projects"


def login(client, _args) -> dict:
    """Force-acquire (userpass) or confirm (apikey) authentication."""
    kind = client.profile.get("type")
    if kind == "userpass":
        session = auth.force_login(client.name, client.profile, client._session)
        cookies = session.get("cookies", {})
        return {
            "authenticated": True,
            "mode": "userpass",
            "profile": client.name,
            "environment": client.env.get("name"),
            "session_cached": True,
            "cookie_names": sorted(cookies.keys()),   # names only, never values
            "expires_at": session.get("expires_at"),
            "web_base": config.web_base(client.profile),
            "login_path": auth.LOGIN_PATH,
        }
    # apikey: nothing to fetch - just confirm the headers are well-formed.
    headers = auth.auth_headers(client.name, client.profile, client._session)
    return {
        "authenticated": True,
        "mode": "apikey",
        "profile": client.name,
        "environment": client.env.get("name"),
        "sends_workspaceid": "workspaceid" in headers,
        "web_base": config.web_base(client.profile),
        "note": ("apikey auth is validated per-request; run check-auth to hit a "
                 "live endpoint"),
    }


def _probe_for(client) -> tuple[str, dict | None, str, str | None]:
    """Choose a read endpoint appropriate to the credential's actual scope.

    A workspace-bound API key should not have to enumerate the account's workspace
    collection merely to prove it can operate its own workspace. Probe the process
    collection in that workspace instead. User sessions and unscoped/master keys
    retain the account-level workspace probe.
    """
    mode = client.profile.get("type")
    workspace_id = client.workspace_id or client.profile.get("workspace_id")
    if mode == "apikey" and workspace_id:
        return (
            _WORKSPACE_PROBE_PATH,
            {"pageNumber": 1, "pageItemCount": 1},
            "workspace",
            workspace_id,
        )
    return _ACCOUNT_PROBE_PATH, None, "account", workspace_id


def _visible_count(body) -> int | None:
    if isinstance(body, list):
        return len(body)
    if isinstance(body, dict):
        for key in ("totalItemCount", "totalCount", "count"):
            value = body.get(key)
            if isinstance(value, int):
                return value
        for key in ("pageItems", "items", "results"):
            value = body.get(key)
            if isinstance(value, list):
                return len(value)
    return None


def _failure_guidance(client, error: ProcesioAPIError) -> dict:
    """Return machine-readable recovery guidance without exposing secrets.

    In particular, ``mode=apikey`` only reports the stored profile type. Agents
    repeatedly interpreted it as a successful authentication signal even when
    ``authenticated`` was false, then probed more endpoints that could add no
    information. A rejected scope-appropriate readiness probe is a hard stop for
    further remote calls.
    """
    mode = client.profile.get("type")
    workspace_id = client.workspace_id or client.profile.get("workspace_id")
    if mode == "apikey" and error.status in {401, 403}:
        return {
            "failure_class": "credential_rejected",
            "hard_stop": True,
            "workspace_id": workspace_id,
            "diagnosis": (
                "The API key name/value/workspace combination was rejected by a "
                "scope-appropriate read. mode='apikey' identifies the stored "
                "profile type; it does not mean authentication succeeded."
            ),
            "next_action": (
                "Do not call other PROCESIO endpoints with this profile. Use only "
                "local non-secret metadata commands (show-credential, "
                "list-credentials, show-environment), then recreate or re-enter "
                "the API key NAME and VALUE for the exact workspace. Retry "
                "check-auth before any other API call."
            ),
        }
    return {
        "failure_class": "authentication_or_service_failure",
        "hard_stop": True,
        "workspace_id": workspace_id,
        "diagnosis": "The live authentication probe failed.",
        "next_action": (
            "Do not continue with workspace operations until check-auth returns "
            "authenticated=true. Diagnose the named profile, environment, and "
            "workspace using non-secret metadata only."
        ),
    }


def check_auth(client, _args) -> dict:
    """Hit a scope-appropriate live read endpoint to confirm the credential."""
    probe_path, query, probe_scope, workspace_id = _probe_for(client)
    try:
        body = client.get(probe_path, query)
    except ProcesioAPIError as e:
        return {
            "authenticated": False,
            "profile": client.name,
            "environment": client.env.get("name"),
            "mode": client.profile.get("type"),
            "probe": probe_path,
            "probe_scope": probe_scope,
            "workspace_id": workspace_id,
            "status": e.status,
            "detail": e.details,
            "web_base": config.web_base(client.profile),
            "auth_base": config.auth_base(client.profile),
            **_failure_guidance(client, e),
        }

    count = _visible_count(body)
    out = {
        "authenticated": True,
        "profile": client.name,
        "environment": client.env.get("name"),
        "web_base": config.web_base(client.profile),
        "mode": client.profile.get("type"),
        "probe": probe_path,
        "probe_scope": probe_scope,
        "workspace_id": workspace_id,
    }
    if probe_scope == "workspace":
        out["processes_visible"] = count
    else:
        out["workspaces_visible"] = count
    return out


def logout(client, _args) -> dict:
    """Clear the cached session (in-process + persistent), best-effort server logOut."""
    name = client.name
    had = (name in auth._MEM_COOKIES) or (profiles.get_token_cache(name) is not None)
    if client.profile.get("type") == "userpass" and had:
        try:
            client.post("/api/Authentication/logOut")
        except ProcesioAPIError:
            pass
    auth.clear_cookies(name)
    return {"profile": name, "cleared_cached_token": had}


ACTIONS = {
    "login": ActionDef(
        func=login, add_args=add_profile_arg, needs_client=True,
        description="Acquire (userpass) or confirm (apikey) authentication; caches the token.",
    ),
    "check-auth": ActionDef(
        func=check_auth, add_args=add_profile_arg, needs_client=True,
        description="Hit a scope-appropriate live read endpoint to verify the profile authenticates.",
    ),
    "logout": ActionDef(
        func=logout, add_args=add_profile_arg, needs_client=True,
        description="Clear the cached Bearer token for a userpass profile.",
    ),
}
