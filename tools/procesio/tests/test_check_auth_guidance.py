"""Regression tests for actionable, scope-correct authentication checks."""
from __future__ import annotations

from tools.procesio import main
from tools.procesio.client import ProcesioClient
from tools.procesio.tests.conftest import FakeResp, FakeSession


def _builder(profile, session):
    return lambda _name: ProcesioClient(
        profile=profile, name="pure-awesomeness", session=session
    )


def test_workspace_apikey_uses_process_collection_as_readiness_probe():
    session = FakeSession(queue=[FakeResp(200, {
        "totalItemCount": 0,
        "pageNumber": 1,
        "pageItemCount": 1,
        "pageItems": [],
    })])
    out = main.dispatch(
        "check-auth",
        ["--workspace-id", "dc28053d-f701-4880-99c2-7d973899d135"],
        client_builder=_builder(
            {"type": "apikey", "key": "NAME", "value": "VALUE"}, session
        ),
    )

    assert out["authenticated"] is True
    assert out["probe"] == "/api/Projects"
    assert out["probe_scope"] == "workspace"
    assert out["processes_visible"] == 0
    call = session.calls[0]
    assert call["url"].endswith("/api/Projects")
    assert call["params"] == {"pageNumber": 1, "pageItemCount": 1}
    assert call["headers"]["workspaceid"] == "dc28053d-f701-4880-99c2-7d973899d135"


def test_apikey_403_is_an_explicit_hard_stop():
    key_handle = "raw-handle-9f3c"
    key_value = "raw-value-7a2d"
    session = FakeSession(queue=[FakeResp(403, None, "Unauthorized")])
    out = main.dispatch(
        "check-auth",
        ["--workspace-id", "dc28053d-f701-4880-99c2-7d973899d135"],
        client_builder=_builder(
            {"type": "apikey", "key": key_handle, "value": key_value}, session
        ),
    )

    assert out["authenticated"] is False
    assert out["mode"] == "apikey"
    assert out["probe"] == "/api/Projects"
    assert out["probe_scope"] == "workspace"
    assert out["failure_class"] == "credential_rejected"
    assert out["hard_stop"] is True
    assert out["workspace_id"] == "dc28053d-f701-4880-99c2-7d973899d135"
    assert "does not mean authentication succeeded" in out["diagnosis"]
    assert "Do not call other PROCESIO endpoints" in out["next_action"]
    rendered = str(out)
    assert key_handle not in rendered and key_value not in rendered


def test_unscoped_apikey_retains_account_workspace_probe():
    session = FakeSession(queue=[FakeResp(200, [])])
    out = main.dispatch(
        "check-auth",
        [],
        client_builder=_builder(
            {"type": "apikey", "key": "NAME", "value": "VALUE"}, session
        ),
    )

    assert out["authenticated"] is True
    assert out["probe"] == "/api/Workspaces"
    assert out["probe_scope"] == "account"
    assert out["workspaces_visible"] == 0


def test_non_auth_probe_failure_still_blocks_workspace_operations():
    session = FakeSession(queue=[FakeResp(500, {"message": "gateway unavailable"})])
    out = main.dispatch(
        "check-auth",
        [],
        client_builder=_builder(
            {"type": "apikey", "key": "NAME", "value": "VALUE"}, session
        ),
    )

    assert out["authenticated"] is False
    assert out["failure_class"] == "authentication_or_service_failure"
    assert out["hard_stop"] is True
    assert "authenticated=true" in out["next_action"]
