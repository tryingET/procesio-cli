from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BEHAVIORAL = ROOT / "skills" / "evals" / "behavioral.json"


def _case(case_id: str) -> dict:
    data = json.loads(BEHAVIORAL.read_text(encoding="utf-8"))
    return next(row for row in data["cases"] if row["id"] == case_id)


def test_mcp_change_case_is_a_read_only_implementation_plan():
    case = _case("mcp-resource-change")
    prompt = case["prompt"].lower()
    expected = case["expected_output"].lower()

    assert prompt.startswith("plan a test-first change")
    assert "read-only" in prompt
    assert "do not claim to edit files or run tests" in prompt
    assert "implementation and verification plan" in expected
    assert "preserve existing get_skill behavior" in expected
    assert "path-confinement tests" in expected
    assert "traversal and symlink escape" in expected
    assert "execution remains unverified" in expected
