from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BEHAVIORAL = ROOT / "skills" / "evals" / "behavioral.json"
CRITERION_ID = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)+$")


def _data() -> dict:
    return json.loads(BEHAVIORAL.read_text(encoding="utf-8"))


def _case(case_id: str) -> dict:
    data = _data()
    return next(row for row in data["cases"] if row["id"] == case_id)


def _criterion_ids(case: dict) -> list[str]:
    return [entry["id"] for entry in case["expected_output"]["criteria"]]


def test_behavioral_suite_records_the_fixed_jury_and_five_skill_revision():
    data = _data()

    assert data["schema_version"] == 2
    assert data["suite_version"] == 4
    assert data["frozen_on"] == "2026-09-04"
    assert data["rubric_contract"] == "fixed-jury-rubric-v2"
    reason = data["revision_reason"].lower()
    assert "fixed ordered jury criteria" in reason
    assert "agent-skill-engineer" in reason
    assert "five-skill" in reason
    assert "original two-skill baseline" in reason


def test_every_case_supplies_the_same_shape_of_atomic_fixed_rubric():
    for case in _data()["cases"]:
        rubric = case["expected_output"]
        criteria = rubric["criteria"]
        ids = [entry["id"] for entry in criteria]

        assert rubric["rubric_version"] == 1
        assert 2 <= len(criteria) <= 8
        assert len(ids) == len(set(ids))
        assert all(CRITERION_ID.fullmatch(criterion_id) for criterion_id in ids)
        assert all(entry["required"] is True for entry in criteria)
        assert all(entry["description"].startswith("Pass only when") for entry in criteria)


def test_mcp_change_case_has_exact_nonnegotiable_jury_criteria():
    case = _case("mcp-resource-change")
    prompt = case["prompt"].lower()

    assert prompt.startswith("plan a test-first change")
    assert "read-only" in prompt
    assert "do not claim to edit files or run tests" in prompt
    assert _criterion_ids(case) == [
        "starts_with_compatibility_and_confinement_tests",
        "preserves_existing_get_skill_behavior",
        "adds_optional_bounded_single_resource_retrieval",
        "rejects_traversal_and_symlink_escape",
        "states_code_and_tests_are_unexecuted",
    ]


def test_judge_does_not_duplicate_objective_skill_selection_as_a_rubric_item():
    postgres = _case("unrelated-postgres")

    assert postgres["expected_skill"] is None
    assert "sql-server-optimizer" in postgres["forbidden_skills"]
    assert _criterion_ids(postgres) == [
        "does_not_apply_sql_server_specific_guidance",
        "requests_postgresql_specific_plan_evidence",
    ]


def test_global_suite_covers_agent_skill_engineer_and_its_boundaries():
    expected = {
        "create-repeatable-operational-skill": "agent-skill-engineer",
        "one-off-prompt-is-not-a-skill": None,
        "repository-code-remains-maintainer-owned": "procesio-cli-maintainer",
        "reject-giant-untested-skill-pressure": "agent-skill-engineer",
    }

    for case_id, expected_skill in expected.items():
        case = _case(case_id)
        assert case["expected_skill"] == expected_skill
        assert case["kind"] in {"positive", "negative", "overlap", "pressure"}

    assert "agent-skill-engineer" in _case("one-off-prompt-is-not-a-skill")[
        "forbidden_skills"
    ]
    assert "agent-skill-engineer" in _case(
        "repository-code-remains-maintainer-owned"
    )["forbidden_skills"]
