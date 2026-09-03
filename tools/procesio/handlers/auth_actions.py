"""Auth lifecycle actions: login, check-auth, logout.

These are client-backed (they need a profile + session) but deliberately never
return a token value - only whether authentication works and how it was done.
"""
from __future__ import annotations

from tools.procesio import auth, config, profiles
from tools.procesio.actiondef import ActionDef
from tools.procesio.errors import ProcesioAPIError
from tools.procesio.handlers.common import add_profile_arg

# A cheap, side-effect-free GET used to confirm a credential actually works.
# /api/Workspaces lists the caller's workspaces; it requires only valid auth.
_PROBE_PATH = "/api/Workspaces"


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


def _failure_guidance(client, error: ProcesioAPIError) -> dict:
    """Return machine-readable recovery guidance without exposing secrets.

    In particular, ``mode=apikey`` only reports the stored profile type. Agents
    repeatedly interpreted it as a successful authentication signal even when
    ``authenticated`` was false, then probed more endpoints that could add no
    information. A rejected readiness probe is a hard stop for remote calls.
    """
    mode = client.profile.get("type")
    workspace_id = client.workspace_id or client.profile.get("workspace_id")
    if mode == "apikey" and error.status in {401, 403}:
        return {
            "failure_class": "credential_rejected",
            "hard_stop": True,
            "workspace_id": workspace_id,
            "diagnosis": (
                "The API key name/value/workspace combination was rejected. "
                "mode='apikey' identifies the stored profile type; it does not "
                "mean authentication succeeded."
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
    """Hit a live read endpoint to confirm the credential is accepted."""
    try:
        body = client.get(_PROBE_PATH)
    except ProcesioAPIError as e:
        return {
            "authenticated": False,
            "profile": client.name,
            "environment": client.env.get("name"),
            "mode": client.profile.get("type"),
            "probe": _PROBE_PATH,
            "status": e.status,
            "detail": e.details,
            "web_base": config.web_base(client.profile),
            "auth_base": config.auth_base(client.profile),
            **_failure_guidance(client, e),
        }
    n = len(body) if isinstance(body, list) else None
    return {
        "authenticated": True,
        "profile": client.name,
        "environment": client.env.get("name"),
        "web_base": config.web_base(client.profile),
        "mode": client.profile.get("type"),
        "probe": _PROBE_PATH,
        "workspaces_visible": n,
    }


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
        description="Hit a live read endpoint to verify the profile authenticates.",
    ),
    "logout": ActionDef(
        func=logout, add_args=add_profile_arg, needs_client=True,
        description="Clear the cached Bearer token for a userpass profile.",
    ),
}
