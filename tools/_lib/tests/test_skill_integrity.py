from __future__ import annotations

from types import SimpleNamespace

from tools._lib.skill_integrity import skill_integrity_errors


def _manifest(**overrides):
    values = {"name": "demo", "description": "Use when testing demo skills.",
              "eval_suite": ""}
    values.update(overrides)
    return SimpleNamespace(**values)


def test_repository_script_path_is_not_mistaken_for_bundled_resource(tmp_path):
    root = tmp_path / "demo"
    root.mkdir()
    skill = root / "SKILL.md"
    skill.write_text(
        "---\nname: demo\ndescription: demo\n---\n"
        "Run `python scripts/run-tool.py demo list`.\n",
        encoding="utf-8",
    )
    assert skill_integrity_errors(_manifest(), skill) == []


def test_missing_reference_is_blocking_when_skill_owns_references(tmp_path):
    root = tmp_path / "demo"
    (root / "references").mkdir(parents=True)
    skill = root / "SKILL.md"
    skill.write_text(
        "---\nname: demo\ndescription: demo\n---\n"
        "Read `references/missing.md`.\n",
        encoding="utf-8",
    )
    assert skill_integrity_errors(_manifest(), skill) == [
        "resource does not exist: references/missing.md"
    ]


def test_missing_eval_suite_is_blocking(tmp_path):
    root = tmp_path / "demo"
    root.mkdir()
    skill = root / "SKILL.md"
    skill.write_text("---\nname: demo\ndescription: demo\n---\n# Demo\n")
    assert skill_integrity_errors(_manifest(eval_suite="evals/evals.json"), skill) == [
        "eval_suite does not exist: evals/evals.json"
    ]


def test_nested_bundled_resource_is_blocking(tmp_path):
    root = tmp_path / "demo"
    nested = root / "references" / "nested"
    nested.mkdir(parents=True)
    (nested / "guide.md").write_text("guide", encoding="utf-8")
    skill = root / "SKILL.md"
    skill.write_text("---\nname: demo\ndescription: demo\n---\n# Demo\n")
    errors = skill_integrity_errors(_manifest(), skill)
    assert "nested bundled resource: references/nested/guide.md" in errors


def test_python_bytecode_caches_are_not_bundled_resources(tmp_path):
    root = tmp_path / "demo"
    cache = root / "scripts" / "__pycache__"
    cache.mkdir(parents=True)
    (cache / "helper.cpython-312.pyc").write_text("bytecode fixture", encoding="utf-8")
    skill = root / "SKILL.md"
    skill.write_text("---\nname: demo\ndescription: demo\n---\n# Demo\n")

    assert skill_integrity_errors(_manifest(), skill) == []
