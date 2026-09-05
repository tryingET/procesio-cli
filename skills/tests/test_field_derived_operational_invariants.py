from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REFERENCES = ROOT / "skills" / "procesio-cli" / "references"


def test_operation_contract_uses_host_enforced_field_gates():
    text = (REFERENCES / "operation-contract.md").read_text(encoding="utf-8")

    assert "ordered required check IDs" in text
    assert "execution agent may collect evidence" in text
    assert "its own `passed` or `passed_with_gap` label is not authority" in text
    assert "separately approved, versioned, narrower remediation" in text
    assert "Scope each phase verdict to that phase's own obligations" in text
    assert "overall project remains `passed_with_gap`" in text
    assert "new local failure may not be disguised as inherited" in text
    assert "complete causal tree" in text


def test_process_lifecycle_preserves_callers_and_counts_children():
    text = (REFERENCES / "process-lifecycle.md").read_text(encoding="utf-8")

    assert "snapshot its public variable IDs" in text
    assert "Preserve existing public input/output IDs" in text
    assert "complete parent/child tree" in text
    assert "remediation for only the missing path" in text


def test_form_e2e_requires_native_result_path_not_manual_dom_proof():
    text = (REFERENCES / "form-e2e.md").read_text(encoding="utf-8")
    notes = (
        ROOT / "tools" / "procesio" / "dto" / "form" / "RUN-PROCESS-RESULT-NOTES.md"
    ).read_text(encoding="utf-8")

    assert "source-owned form-event result contract" in text
    assert "variable-instance collection" in text
    assert "one real native form action" in text
    assert "Do not call the SPA's writer manually" in text
    assert "direct CLI/subprocess callers still receive" in text
    assert "no secret default" in text

    assert "`content.variable`" in notes
    assert "compatibility envelope" in notes
    assert "The example is structural, not a DTO to copy literally" in notes
    assert "Do not call the SPA writer manually" in notes


def test_schedule_playbook_treats_process_inputs_as_secret_bearing():
    text = (REFERENCES / "schedules-webhooks.md").read_text(encoding="utf-8")
    notes = (
        ROOT / "tools" / "procesio" / "SCHEDULE-INPUT-SECURITY-NOTES.md"
    ).read_text(encoding="utf-8")
    handler = (
        ROOT / "tools" / "procesio" / "handlers" / "schedules.py"
    ).read_text(encoding="utf-8")
    notes_normalized = " ".join(notes.split())

    assert "Literal `processInputs` values may be persisted and returned unmasked" in text
    assert "get-schedule --redact-process-inputs" in text
    assert "stage the payload through a protected `@file`" in text
    assert "clean local-file sweep does not prove" in text
    assert "treat it as disclosed" in text
    assert "Redact every literal schedule input value" in text

    # Natural-language requirements must survive harmless Markdown reflow.
    assert "GET /api/Schedules/{scheduleId}` returns those values without masking" in notes_normalized
    assert "get-schedule --redact-process-inputs" in notes_normalized
    assert "raw get mode can still expose clear values" in notes_normalized
    assert "a protected `@file`" in notes_normalized
    assert "rotate it" in notes_normalized
    assert "clean local-file sweep alone does not prove" in notes_normalized

    assert "SCHEDULE-INPUT-SECURITY-NOTES.md" in handler
    assert "preserves the raw DTO by default" in handler
    assert "--redact-process-inputs" in handler
    assert "_redact_process_inputs" in handler


def test_webhook_playbook_uses_whole_body_model_and_bounded_adapter():
    text = (REFERENCES / "schedules-webhooks.md").read_text(encoding="utf-8")

    assert "generated webhook body is a typed model object" in text
    assert "one compatible model-typed process input" in text
    assert "bounded adapter process" in text
    assert "Do not repeat a failed per-field primitive mapping" in text
    assert "complete trigger-target/child instance tree" in text


def test_webhook_source_description_no_longer_claims_primitive_fanout():
    text = (
        ROOT / "tools" / "procesio" / "dto" / "webhook" / "description.md"
    ).read_text(encoding="utf-8")
    normalized = " ".join(text.split())

    assert "as **one model object**" in text
    assert "does not provide a field-by-field mapping table" in text
    assert "use a bounded adapter process" in normalized
    assert "binding webhook payload fields to the flow's input variables" not in text
