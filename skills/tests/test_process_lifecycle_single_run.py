from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PLAYBOOK = ROOT / "skills" / "procesio-cli" / "references" / "process-lifecycle.md"


def test_process_lifecycle_requires_one_representative_execution():
    text = PLAYBOOK.read_text(encoding="utf-8")
    lower = text.lower()

    assert "exactly once" in lower
    assert "one execution path only" in lower
    assert "do not also call `run-process`" in lower
    assert "verify --run" in lower
    assert "status alone is not proof of the expected output value" in lower
