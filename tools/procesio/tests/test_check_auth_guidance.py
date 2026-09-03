"""Regression tests for actionable, non-secret authentication failures."""
from __future__ import annotations

from tools.procesio import main
from tools.procesio.client import ProcesioClient
from tools.procesio.tests.conftest import FakeResp, FakeSession


def _builder(profile, session):
    return lambda _name: ProcesioClient(
        profile=profile, name="pure-awesomeness", session=session
    )


def test_apikey_403_is_an_explicit_hard_stop():
    session = FakeSession(queue=[FakeResp(403, None, "Unauthorized")])
    out = main.dispatch(
        "check-auth",
        ["--workspace-id", "dc28053d-f701-4880-99c2-7d973899d135"],
        client_builder=_builder(
            {"type": "apikey", "key": "NAME", "value": "VALUE"}, session
        ),
    )

    assert out["authenticated"] is False
    assert out["mode"] == "apikey"
    assert out["failure_class"] == "credential_rejected"
    assert out["hard_stop"] is True
    assert out["workspace_id"] == "dc28053d-f701-4880-99c2-7d973899d135"
    assert "does not mean authentication succeeded" in out["diagnosis"]
    assert "Do not call other PROCESIO endpoints" in out["next_action"]
    assert "NAME" not in str(out) and "VALUE" not in str(out)


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
