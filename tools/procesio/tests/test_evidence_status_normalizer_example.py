from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[3]
CONFIG = ROOT / "examples" / "procesio" / "evidence-status-normalizer.process.json"
SAMPLE = ROOT / "examples" / "procesio" / "evidence-status-normalizer.sample-payload.json"
SCHEMA = ROOT / "tools" / "procesio" / "dto" / "process" / "config.schema.json"


def test_evidence_status_normalizer_is_schema_valid_and_side_effect_free():
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    Draft202012Validator(schema).validate(config)

    assert config["title"] == "CLI Utility 01 - Evidence Status Normalizer"
    assert config["edges"] == [["start", "normalize"], ["normalize", "stop"]]
    assert "webhooks" not in config
    assert len(config["actions"]) == 1

    action = config["actions"][0]
    assert action["action"] == "Node"
    assert action["params"]["Timeout"] == 60
    assert action["params"]["Single Result"] == {"var": "normalized"}
    assert action["params"]["Error"] == {"var": "script_error"}

    code = action["params"]["Code"]["template"]
    assert action["params"]["Code"]["vars"] == ["status"]
    assert code.count("<%0%>") == 1
    assert "??" not in code
    assert "ACCEPT_EVIDENCE" in code
    assert "RESUME_CHECKPOINT" in code
    assert "DIAGNOSE_INFRASTRUCTURE" in code


def test_representative_payload_matches_the_frozen_gate5_success_shape():
    payload = json.loads(SAMPLE.read_text(encoding="utf-8"))
    status = payload["status"]

    assert status["status"] == "complete"
    assert status["stop_reason"] == "gate5_series_passed"
    assert status["gate5_evidence"] is True
    assert status["completed_observations"] == status["total_observations"] == 360
    assert status["remaining_observations"] == 0
