#!/usr/bin/env python3
"""Check skill ownership, freshness metadata, evaluation links, and release state."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools._lib.manifest import load_skill  # noqa: E402

DEFAULT_SKILLS = ROOT / "skills"
DEFAULT_STATUS = DEFAULT_SKILLS / "evals" / "gates.json"
EXPECTED_GATES = set(range(7))


def check_skills(skills_root: Path, *, max_age_days: int | None = None,
                 today: date | None = None) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    now = today or date.today()
    paths = sorted(skills_root.glob("*/SKILL.md"))
    if not paths:
        return [{"skill": "<repository>", "code": "no-skills", "message": "no skills found"}]
    for skill_md in paths:
        if skill_md.parent.name.startswith("_") or skill_md.parent.name == "tests":
            continue
        try:
            manifest = load_skill(skill_md)
        except Exception as exc:  # noqa: BLE001
            findings.append({"skill": skill_md.parent.name, "code": "invalid-skill",
                             "message": str(exc)})
            continue
        required = {
            "owner": manifest.owner,
            "last_verified": manifest.last_verified,
            "baseline_version": manifest.baseline_version,
            "eval_suite": manifest.eval_suite,
            "source_policy": manifest.source_policy,
        }
        for field, value in required.items():
            if not value:
                findings.append({
                    "skill": manifest.name,
                    "code": f"missing-{field.replace('_', '-')}",
                    "message": f"{field} is required for published skills",
                })
        if not manifest.routing or not manifest.routing.triggers:
            findings.append({"skill": manifest.name, "code": "missing-routing",
                             "message": "curated routing triggers are required"})
        if (max_age_days is not None and manifest.source_policy == "timestamped"
                and manifest.last_verified is not None):
            age = (now - manifest.last_verified).days
            if age < 0:
                findings.append({"skill": manifest.name, "code": "future-verification-date",
                                 "message": f"last_verified is {abs(age)} days in the future"})
            elif age > max_age_days:
                findings.append({"skill": manifest.name, "code": "stale-timestamped-skill",
                                 "message": f"last verified {age} days ago; maximum is {max_age_days}"})
    return findings


def check_status(path: Path, *, require_release_eligible: bool = False) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    try:
        raw: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [{"skill": "<repository>", "code": "invalid-gate-status", "message": str(exc)}]
    rows = raw.get("gates") if isinstance(raw, dict) else None
    if not isinstance(rows, list):
        return [{"skill": "<repository>", "code": "invalid-gate-status",
                 "message": "gates must be a list"}]
    ids = [row.get("id") for row in rows if isinstance(row, dict)]
    if set(ids) != EXPECTED_GATES or len(ids) != len(set(ids)):
        findings.append({"skill": "<repository>", "code": "incomplete-gate-set",
                         "message": "gate ids must be unique integers 0 through 6"})
    allowed = {"passed", "pending-external-run", "infrastructure-complete", "blocked"}
    for row in rows:
        if not isinstance(row, dict):
            continue
        if row.get("status") not in allowed:
            findings.append({"skill": "<repository>", "code": "invalid-gate-state",
                             "message": f"gate {row.get('id')} has invalid status {row.get('status')!r}"})
        for evidence in row.get("evidence") or []:
            target = ROOT / str(evidence)
            if not target.exists():
                findings.append({"skill": "<repository>", "code": "missing-gate-evidence",
                                 "message": f"gate {row.get('id')} evidence is missing: {evidence}"})
    eligible = bool(raw.get("release_eligible"))
    blockers = raw.get("release_blockers") or []
    all_passed = len(rows) == 7 and all(
        isinstance(row, dict) and row.get("status") == "passed" for row in rows
    )
    if eligible and (not all_passed or blockers):
        findings.append({"skill": "<repository>", "code": "false-release-eligibility",
                         "message": "release_eligible requires every gate passed and no blockers"})
    if require_release_eligible and not eligible:
        findings.append({"skill": "<repository>", "code": "release-blocked",
                         "message": "; ".join(str(item) for item in blockers) or "release not eligible"})
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skills-root", type=Path, default=DEFAULT_SKILLS)
    parser.add_argument("--status-file", type=Path, default=DEFAULT_STATUS)
    parser.add_argument("--max-age-days", type=int)
    parser.add_argument("--require-release-eligible", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    findings = check_skills(args.skills_root, max_age_days=args.max_age_days)
    findings += check_status(args.status_file,
                             require_release_eligible=args.require_release_eligible)
    report = {"finding_count": len(findings), "findings": findings,
              "release_check": args.require_release_eligible}
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        for finding in findings:
            print(f"ERROR: {finding['skill']}: {finding['code']}: {finding['message']}")
        print(f"{len(findings)} governance finding(s)")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
