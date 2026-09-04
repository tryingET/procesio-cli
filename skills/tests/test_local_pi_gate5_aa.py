from __future__ import annotations

import importlib.util
import json
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


def test_resume_batch_budget_counts_only_new_observations():
    remaining, observations, calls = RUNNER._batch_counts(
        total_observations=80,
        completed_observations=12,
        max_new_observations=8,
    )

    assert remaining == 68
    assert observations == 8
    assert calls == 16


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


def test_harness_command_is_resumable_aa_and_uses_snapshot_files(tmp_path):
    corpus_a = tmp_path / "a"
    corpus_b = tmp_path / "b"
    results = tmp_path / "results"
    evals = corpus_a / "evals" / "behavioral.json"
    thresholds = corpus_a / "evals" / "gate5-thresholds.json"

    command = RUNNER._build_harness_command(
        corpus_a=corpus_a,
        corpus_b=corpus_b,
        results=results,
        evals=evals,
        thresholds=thresholds,
        repetitions=5,
        seed=20260902,
        timeout=900,
        resume=True,
        max_new_observations=8,
        platform="posix",
    )

    assert command[command.index("--mode") + 1] == "aa"
    assert command[command.index("--candidate-root") + 1] == str(corpus_a)
    assert command[command.index("--baseline-root") + 1] == str(corpus_b)
    assert command[command.index("--evals") + 1] == str(evals)
    assert command[command.index("--thresholds") + 1] == str(thresholds)
    assert command[command.index("--repetitions") + 1] == "5"
    assert command[command.index("--seed") + 1] == "20260902"
    assert command[command.index("--max-new-observations") + 1] == "8"
    assert "--resume" in command
    runner_value = command[command.index("--runner") + 1]
    assert "pi-skill-eval-runner-strict.py" in runner_value


def test_windows_runner_command_preserves_backslash_paths():
    value = RUNNER._join_argv(
        [r"C:\repo path\.venv\Scripts\python.exe", r"C:\repo path\strict.py"],
        platform="nt",
    )

    assert r"C:\repo path\.venv\Scripts\python.exe" in value
    assert r"C:\repo path\strict.py" in value


def test_legacy_checkpoint_requires_exact_observation_confirmation(tmp_path):
    metadata_path = tmp_path / "run-metadata.json"
    results = tmp_path / "results"
    results.mkdir()
    (results / "runs.jsonl").write_text(
        json.dumps({"evaluation_model": "opencode-go/muse-spark-1.3-contributor"}) + "\n",
        encoding="utf-8",
    )
    expected = {
        "schema_version": 1,
        "kind": "gate5-aa-run-metadata",
        "model": "opencode-go/muse-spark-1.3-contributor",
        "provider": None,
        "thinking": "medium",
    }

    with pytest.raises(ValueError, match="confirm-existing-observations 12"):
        RUNNER._validate_or_adopt_metadata(
            metadata_path,
            expected,
            completed=12,
            confirm_existing=None,
        )

    metadata = RUNNER._validate_or_adopt_metadata(
        metadata_path,
        expected,
        completed=12,
        confirm_existing=12,
    )
    assert metadata["adopted_legacy_checkpoint"] is True
    assert metadata["operator_confirmed_existing_observations"] == 12


def test_resume_metadata_rejects_thinking_level_change(tmp_path):
    path = tmp_path / "run-metadata.json"
    results = tmp_path / "results"
    results.mkdir()
    original = {
        "schema_version": 1,
        "kind": "gate5-aa-run-metadata",
        "model": "opencode-go/muse-spark-1.3-contributor",
        "provider": None,
        "thinking": "medium",
    }
    path.write_text(json.dumps(original), encoding="utf-8")
    changed = {**original, "thinking": "low"}

    with pytest.raises(ValueError, match="thinking changed"):
        RUNNER._validate_or_adopt_metadata(
            path,
            changed,
            completed=12,
            confirm_existing=12,
        )
