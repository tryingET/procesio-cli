from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SKILL_ROOT = ROOT / "skills" / "agent-skill-engineer"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


SCAFFOLD = _load(
    "agent_skill_scaffold",
    SKILL_ROOT / "scripts" / "scaffold_skill.py",
)
AUDIT = _load(
    "agent_skill_audit",
    SKILL_ROOT / "scripts" / "audit_skill.py",
)


def _frontmatter(path: Path) -> dict:
    lines = path.read_text(encoding="utf-8").splitlines()
    end = lines[1:].index("---") + 1
    value = yaml.safe_load("\n".join(lines[1:end]))
    assert isinstance(value, dict)
    return value


def test_meta_skill_passes_its_deterministic_audit():
    report = AUDIT.audit_skill(SKILL_ROOT)

    assert report["passed"] is True
    assert report["errors"] == 0
    assert report["warnings"] == 0
    assert report["quality_score"] == 100


def test_scaffold_is_path_confined_governed_and_no_overwrite(tmp_path):
    parser = SCAFFOLD._parser()
    args = parser.parse_args(
        [
            "incident-triage",
            "--root",
            str(tmp_path),
            "--description",
            "Triage recurring incidents. Use when an incident report needs a bounded diagnostic workflow.",
            "--profile",
            "governed",
            "--owner",
            "platform team",
            "--baseline-version",
            "abc123",
            "--trigger",
            "triage a recurring production incident",
        ]
    )

    result = SCAFFOLD.scaffold(args)
    target = tmp_path / "incident-triage"

    assert result["created"] is True
    assert (target / "SKILL.md").is_file()
    assert (target / "evals" / "evals.json").is_file()
    frontmatter = _frontmatter(target / "SKILL.md")
    assert frontmatter["name"] == "incident-triage"
    assert frontmatter["owner"] == "platform team"
    assert frontmatter["eval_suite"] == "evals/evals.json"
    suite = json.loads((target / "evals" / "evals.json").read_text())
    assert {case["kind"] for case in suite["cases"]} == {
        "positive",
        "negative",
        "overlap",
        "pressure",
    }
    assert suite["rubric_contract"] == "fixed-jury-rubric-v2"

    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        SCAFFOLD.scaffold(args)

    with pytest.raises(ValueError, match="lowercase"):
        bad = argparse.Namespace(**{**vars(args), "name": "../escape"})
        SCAFFOLD.scaffold(bad)


def test_audit_rejects_dynamic_jury_and_unsafe_reference(tmp_path):
    root = tmp_path / "broken-skill"
    (root / "evals").mkdir(parents=True)
    (root / "SKILL.md").write_text(
        "---\n"
        "name: broken-skill\n"
        "description: Use when auditing a broken example.\n"
        "version: 1.0.0\n"
        "owner: test\n"
        "last_verified: 2026-09-04\n"
        "baseline_version: abc\n"
        "eval_suite: evals/evals.json\n"
        "source_policy: stable\n"
        "routing:\n  triggers: [audit a broken example]\n"
        "---\n\n"
        "# Broken\n\n"
        "## Boundary\nBounded.\n\n"
        "## Workflow\nRead [outside](../outside.md).\n\n"
        "## Verification\nInspect the report.\n",
        encoding="utf-8",
    )
    (root / "evals" / "evals.json").write_text(
        json.dumps(
            {
                "skill_name": "broken-skill",
                "evals": [
                    {
                        "id": "one",
                        "kind": "positive",
                        "prompt": "Do it",
                        "expected_output": "Be good and safe.",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    report = AUDIT.audit_skill(root)
    codes = {item["code"] for item in report["findings"]}

    assert report["passed"] is False
    assert "unsafe-reference" in codes
    assert "dynamic-jury-rubric" in codes


def test_every_published_skill_uses_fixed_atomic_eval_rubrics():
    criterion_id = AUDIT.CRITERION_RE
    case_kinds = AUDIT.CASE_KINDS

    for skill_md in sorted((ROOT / "skills").glob("*/SKILL.md")):
        frontmatter = _frontmatter(skill_md)
        suite_path = skill_md.parent / frontmatter["eval_suite"]
        suite = json.loads(suite_path.read_text(encoding="utf-8"))
        cases = suite["cases"]

        assert suite["schema_version"] >= 2, skill_md.parent.name
        assert suite["skill_name"] == frontmatter["name"]
        assert suite["rubric_contract"] == "fixed-jury-rubric-v2"
        assert {case["kind"] for case in cases} == case_kinds

        for case in cases:
            expected = case["expected_output"]
            criteria = expected["criteria"]
            ids = [entry["id"] for entry in criteria]
            assert expected["rubric_version"] >= 1
            assert 2 <= len(criteria) <= 8
            assert len(ids) == len(set(ids))
            assert all(criterion_id.fullmatch(item) for item in ids)
            assert all(entry["description"].startswith("Pass only when") for entry in criteria)
            assert all(isinstance(entry["required"], bool) for entry in criteria)
