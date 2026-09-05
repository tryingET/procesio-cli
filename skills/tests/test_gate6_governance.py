from __future__ import annotations

import importlib.util
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


governance = _load("check_skill_governance", ROOT / "scripts" / "check-skill-governance.py")
series = _load("verify_skill_eval_series", ROOT / "scripts" / "verify-skill-eval-series.py")


def _skill(root: Path, *, verified: str = "2026-09-03", owner: str = "owner") -> None:
    path = root / "demo"
    (path / "evals").mkdir(parents=True)
    (path / "evals" / "evals.json").write_text("{}", encoding="utf-8")
    (path / "SKILL.md").write_text(
        "---\nname: demo\ndescription: Use when testing.\nversion: 1.0.0\n"
        f"owner: {owner}\nlast_verified: {verified}\nbaseline_version: abc\n"
        "eval_suite: evals/evals.json\nsource_policy: timestamped\n"
        "routing:\n  triggers: [test]\n---\n# Demo\n",
        encoding="utf-8",
    )


def test_governance_requires_metadata_and_checks_freshness(tmp_path):
    _skill(tmp_path, verified="2026-01-01")
    findings = governance.check_skills(
        tmp_path, max_age_days=120, today=date(2026, 9, 3)
    )
    assert any(row["code"] == "stale-timestamped-skill" for row in findings)


def test_release_status_cannot_claim_eligibility_with_pending_gate(tmp_path):
    status = tmp_path / "gates.json"
    status.write_text(json.dumps({
        "release_eligible": True,
        "release_blockers": [],
        "gates": [{"id": value, "status": "passed" if value < 5 else "blocked"}
                  for value in range(7)],
    }), encoding="utf-8")
    findings = governance.check_status(status)
    assert any(row["code"] == "false-release-eligibility" for row in findings)


def test_two_matching_passing_reports_clear_series():
    report = {"candidate_fingerprint": "candidate", "baseline_fingerprint": "baseline",
              "gate": {"passed": True}}
    assert series.verify([report, report], 2)["passed"] is True
    assert series.verify([report], 2)["passed"] is False


def test_gate5_pass_is_scoped_and_release_stays_blocked_on_skill_drift():
    status = json.loads((ROOT / "skills" / "evals" / "gates.json").read_text())
    evidence = json.loads(
        (ROOT / "skills" / "evals" / "local-pi-gate5-suite-v4-passed.json").read_text()
    )

    gate5 = next(row for row in status["gates"] if row["id"] == 5)
    assert gate5["status"] == "passed"
    assert gate5["evaluated_candidate_commit"] == evidence["result"]["candidate_commit"]
    assert gate5["evaluated_candidate_fingerprint"] == evidence["result"]["candidate_fingerprint"]
    assert evidence["result"]["gate5_evidence"] is True
    assert evidence["series_verification"]["passed"] is True
    assert evidence["result"]["completed_observations"] == 360

    assert status["release_eligible"] is False
    assert any(
        "current loaded skill corpus" in blocker
        and gate5["evaluated_candidate_commit"] in blocker
        for blocker in status["release_blockers"]
    )
