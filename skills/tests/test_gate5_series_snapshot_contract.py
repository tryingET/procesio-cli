from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "run-local-pi-gate5-series-unattended.py"


def test_formal_series_exports_tracked_candidate_and_baseline_commits():
    text = SCRIPT.read_text(encoding="utf-8")

    assert '_export_git_subtree("HEAD", "skills", candidate)' in text
    assert '_export_git_subtree(baseline_ref, "skills", baseline)' in text
    assert "shutil.copytree(candidate, control)" in text
    assert "shutil.copytree(CURRENT_SKILLS, candidate)" not in text
    assert "Local pycache" in text
