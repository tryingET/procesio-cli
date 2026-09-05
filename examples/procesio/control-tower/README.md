# PROCESIO Control Tower

`PROCESIO Control Tower — Automation Evidence & Founder Briefing` is a retained operational project for the `procesio-cli-pure-awesomeness` workspace. It turns the repository's real evaluation and field-trial evidence into an idempotent ledger, a founder-readable PDF briefing, and safe next actions.

It is deliberately not a throwaway showcase. Once deployed, future CLI/skill work can submit evidence through an authenticated local caller or the published Mission Control form. A weekly orchestrator refreshes public repository pulse data and generates a new briefing.

## What it exercises

The build contract covers the broad operational surface represented by the `procesio-cli` skill:

- workspace-scoped authentication and inventory;
- data model + native data-store lifecycle and row verification;
- compact process DTOs, validation, audit, execution, and direct output reads;
- Node scripting, error outputs, Decisional, Join, For Each, and Call Subprocess;
- custom response mapping;
- connector-builder with a safe public GitHub OpenAPI contract;
- document template and generated PDF verification;
- styled form creation and real-browser E2E;
- temporary webhook lifecycle with cleanup;
- disabled-first schedule creation and controlled enablement;
- project export and ledger CSV verification.

## Files

- `control-tower.project.json` — exact retained-resource names, caps, security policy, and acceptance criteria.
- `control-tower.field-contract.md` — six gated execution phases and required evidence.
- `phase05-remediation.field-contract.md` — separately approved repair contract for native form-result and whole-body webhook proof when the original Phase 05 gaps are present.
- `token-rotation.field-contract.md` — separately approved revocation and replacement contract when a retained access token entered a transcript or ordinary artifact.
- `github-public-pulse.openapi.json` — two-operation, read-only public GitHub connector source.
- `seed-evidence.json` — real repository evaluation and field-trial records used to seed the ledger.
- `../../../scripts/run-procesio-control-tower.py` — resumable PEP 723/uv coordinator that drives local Pi with `zai/glm-5.3` at `high` reasoning.
- `../../../scripts/run-procesio-control-tower-remediation.py` — canonical fixed-check functional remediation and finish entry point; it freezes the complete operational skill package before resuming field work.
- `../../../scripts/run-procesio-control-tower-token-rotation.py` — fixed-check security remediation that rotates an exposed Control Tower token without putting either value in the agent prompt or evidence.

## Preview

```bash
uv run --script scripts/run-procesio-control-tower.py --dry-run
```

The preview makes no model or PROCESIO calls.

## Build or resume

```bash
uv run --script scripts/run-procesio-control-tower.py \
  --confirm BUILD_PROCESIO_CONTROL_TOWER_V1
```

The default model is exactly `zai/glm-5.3` with thinking level `high`. The coordinator refuses to silently substitute a different provider/model. Override only when explicitly intended:

```bash
uv run --script scripts/run-procesio-control-tower.py \
  --model opencode-go/glm-5.3 \
  --thinking high \
  --confirm BUILD_PROCESIO_CONTROL_TOWER_V1
```

Each phase runs in a fresh Pi context, reads the same committed contract, and writes a checkpoint report under `scratchpad/procesio-control-tower-v1/phases/`. A later invocation skips passed phases. It stops rather than automatically repeating a phase after a missing or ambiguous report, because the phase may already have committed platform state.

## Repair the known Phase 05 functional gaps

When the existing Phase 05 report contains the observed `form-sync-result-rendering` and `webhook-field-mapping` gaps, do not edit it to `passed` and do not loosen the original coordinator. Run the separately approved functional remediation:

```bash
uv run --script scripts/run-procesio-control-tower-remediation.py \
  --confirm REMEDIATE_AND_FINISH_PROCESIO_CONTROL_TOWER_V1 \
  --max-hours 8
```

The remediation:

- snapshots the entire `procesio-cli` skill package into the gitignored run root and verifies its fingerprint on resume;
- keeps the original Phase 05 report and logs as evidence;
- repairs the form's real native synchronous result path while preserving direct callers;
- uses a temporary whole-body webhook adapter rather than unsupported primitive fan-out;
- permits one form submission, one webhook delivery, and at most five process instances including nested children;
- deletes the temporary webhook and adapter;
- promotes Phase 05 only after three fixed-check stage reports pass host validation;
- then requests the export/audit Phase 06.

## Rotate the access token after transcript exposure

If any remediation report records that the clear token was displayed in a model transcript, log, screenshot, or ordinary artifact, local redaction is not completion. The credential must be treated as disclosed. Phase 06 is blocked until a separate rotation attestation exists.

Preview the exact checks and budget without generating a replacement:

```bash
uv run --script scripts/run-procesio-control-tower-token-rotation.py --dry-run
```

Run the approved rotation:

```bash
uv run --script scripts/run-procesio-control-tower-token-rotation.py \
  --model 'zai/glm-5.3' \
  --thinking high \
  --run-root "$PWD/scratchpad/procesio-control-tower-v1" \
  --max-hours 2 \
  --confirm ROTATE_PROCESIO_CONTROL_TOWER_ACCESS_TOKEN_V1
```

The rotation launcher:

- generates the replacement locally and places only its path and SHA-256 in the acting-agent prompt;
- freezes a new operational skill snapshot containing the redacted schedule-read contract;
- changes only the ingest token hash and the existing schedule's bound token;
- uses protected `@file` payloads and `get-schedule --redact-process-inputs`;
- runs the old token once to prove denial and the new token once to prove acceptance;
- permits exactly two direct process runs, at most three total instances, and one ledger row;
- scans the complete run root and acting-agent log for both clear token values;
- atomically replaces the mode-`0600` local token source only after platform proof;
- preserves the original Phase 05 report, adds security-remediation lineage, and explicitly records that redaction did not erase the incident;
- archives and removes the pre-rotation Phase 06 report, final report, deployment manifest, project export, and CSV because they describe stale state;
- writes the token-rotation attestation last.

There are no automatic retries. A stopped or missing report may follow committed platform state; inspect `remediation/token-rotation/status.json` before resuming the same command.

## Rerun Phase 06 from the rotated state

After token rotation passes, run the canonical remediation/finish command again:

```bash
uv run --script scripts/run-procesio-control-tower-remediation.py \
  --confirm REMEDIATE_AND_FINISH_PROCESIO_CONTROL_TOWER_V1 \
  --max-hours 8
```

The frozen Phase 06 bridge now:

- requires the valid rotation attestation when exposure is recorded;
- forbids raw schedule reads and requires redacted process-input evidence;
- audits and exports the post-rotation state;
- scopes Phase 06 to `passed` when all of its own checks pass;
- keeps Phase 03's approved custom-connector fallback only in the aggregate project lineage.

For runs with no credential exposure, a completed Phase 06 report that accidentally copied only the inherited Phase 03 gap can still be normalized without model or platform calls. Any new local gap, failed check, missing artifact, unknown outcome, or unremediated exposure blocks that path.

## Intended retained outcome

- one Evidence Record data model;
- one Evidence Ledger data store;
- four Control Tower processes plus the pre-existing immutable normalizer;
- one safe public GitHub connector, or a documented non-secret Call API fallback;
- one founder-brief document template;
- one published Mission Control form;
- one enabled weekly schedule after manual proof;
- zero retained anonymous webhooks;
- one current project export and one current ledger CSV in local gitignored evidence storage.

The correct final verdict scopes are Phase 05 `passed` with functional and security-remediation lineage, Phase 06 `passed`, and aggregate project `passed_with_gap` only for Phase 03's predeclared connector fallback.

The weekly schedule is intentionally small—four runs per month with a five-minute per-run ceiling—so the free 30-hour monthly platform allowance is converted into ongoing value rather than consumed for spectacle.
