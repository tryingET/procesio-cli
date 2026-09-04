from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "run-local-pi-gate5-aa.py"
SPEC = importlib.util.spec_from_file_location("run_local_pi_gate5_aa", SCRIPT)
assert SPEC and SPEC.loader
RUNNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNNER)


def test_formal_suite_call_budget_is_explicit():
    observations, calls = RUNNER._expected_counts(case_count=8, repetitions=5)

    assert observations == 80
    assert calls == 160


def test_corpora_are_independent_byte_equal_copies(tmp_path):
    source = tmp_path / "skills"
    source.mkdir()
    (source / "SKILL.md").write_text("example\n", encoding="utf-8")
    run_root = tmp_path / "run"

    corpus_a, corpus_b = RUNNER._copy_independent_corpora(source, run_root)

    assert corpus_a != corpus_b
    assert (corpus_a / "SKILL.md").read_bytes() == (corpus_b / "SKILL.md").read_bytes()
    (corpus_a / "SKILL.md").write_text("changed\n", encoding="utf-8")
    assert (corpus_b / "SKILL.md").read_text(encoding="utf-8") == "example\n"


def test_existing_run_directory_is_not_deleted(tmp_path):
    source = tmp_path / "skills"
    source.mkdir()
    run_root = tmp_path / "run"
    run_root.mkdir()
    marker = run_root / "keep.txt"
    marker.write_text("keep", encoding="utf-8")

    with pytest.raises(FileExistsError):
        RUNNER._copy_independent_corpora(source, run_root)

    assert marker.read_text(encoding="utf-8") == "keep"


def test_harness_command_is_aa_and_uses_distinct_roots(tmp_path):
    corpus_a = tmp_path / "a"
    corpus_b = tmp_path / "b"
    results = tmp_path / "results"

    command = RUNNER._build_harness_command(
        corpus_a=corpus_a,
        corpus_b=corpus_b,
        results=results,
        repetitions=5,
        seed=20260902,
        timeout=900,
        platform="posix",
    )

    assert command[command.index("--mode") + 1] == "aa"
    assert command[command.index("--candidate-root") + 1] == str(corpus_a)
    assert command[command.index("--baseline-root") + 1] == str(corpus_b)
    assert command[command.index("--repetitions") + 1] == "5"
    assert command[command.index("--seed") + 1] == "20260902"
    runner_value = command[command.index("--runner") + 1]
    assert "pi-skill-eval-runner-strict.py" in runner_value


def test_windows_runner_command_preserves_backslash_paths():
    value = RUNNER._join_argv(
        [r"C:\repo path\.venv\Scripts\python.exe", r"C:\repo path\strict.py"],
        platform="nt",
    )

    assert r"C:\repo path\.venv\Scripts\python.exe" in value
    assert r"C:\repo path\strict.py" in value
