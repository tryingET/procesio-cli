#!/usr/bin/env python3
"""Require consecutive passing behavioral-evaluation reports before release."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def verify(reports: list[dict[str, Any]], required: int) -> dict[str, Any]:
    reasons: list[str] = []
    if len(reports) < required:
        reasons.append(f"{len(reports)} reports supplied; {required} required")
    candidate = {report.get("candidate_fingerprint") for report in reports}
    baseline = {report.get("baseline_fingerprint") for report in reports}
    if len(candidate) > 1:
        reasons.append("candidate fingerprints differ across reports")
    if len(baseline) > 1:
        reasons.append("baseline fingerprints differ across reports")
    for index, report in enumerate(reports, 1):
        if not bool((report.get("gate") or {}).get("passed")):
            reasons.append(f"report {index} did not pass its behavioral gate")
    return {
        "schema_version": 1,
        "passed": not reasons,
        "required_consecutive_clean_runs": required,
        "report_count": len(reports),
        "candidate_fingerprint": next(iter(candidate), None) if len(candidate) == 1 else None,
        "baseline_fingerprint": next(iter(baseline), None) if len(baseline) == 1 else None,
        "reasons": reasons,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reports", nargs="+", type=Path)
    parser.add_argument("--thresholds", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    thresholds = json.loads(args.thresholds.read_text(encoding="utf-8"))
    required = int(thresholds.get("required_consecutive_clean_runs", 2))
    reports = [json.loads(path.read_text(encoding="utf-8")) for path in args.reports]
    result = verify(reports, required)
    rendered = json.dumps(result, indent=2, sort_keys=True)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
