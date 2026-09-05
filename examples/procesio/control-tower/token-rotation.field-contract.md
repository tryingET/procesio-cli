# PROCESIO Control Tower v1 — access-token rotation contract

This is a separately approved security remediation for the access token used by the
Control Tower ingest process, Mission Control form, and weekly schedule. It does not
rewrite the Phase 05 functional evidence and it does not claim that deleting or
redacting a local copy erases an earlier disclosure.

## Why this remediation is required

During the Phase 05 remediation, the clear access token was printed into the acting
agent's conversation transcript while instance variables were inspected. A later
schedule read also returned the literal value stored in `processInputs`. Local copies
were redacted, but the original Phase 05 remediation contract explicitly prohibited
printing the token and required `no_secret_exposure` before promotion.

Therefore:

- the form-result and whole-body webhook outcomes remain useful functional evidence;
- the old token must be treated as disclosed;
- Stage 05R-3's `no_secret_exposure:true` claim is not accepted as historical fact;
- the old token must be revoked by changing the ingest hash and every retained caller;
- pre-rotation Phase 06 exports and reports are stale after the credential changes;
- Phase 06 must be rerun from current state after rotation.

The original stage reports, logs, and promoted Phase 05 report remain preserved. This
contract adds attributable security-remediation lineage; it does not edit those
artifacts in place.

## Fixed target

- project: `procesio-control-tower-v1`
- profile: `pure-awesomeness`
- environment: `Internal-PROD`
- workspace ID: `dc28053d-f701-4880-99c2-7d973899d135`
- run root: `scratchpad/procesio-control-tower-v1`
- retained ingest process: `CLI Control Tower 01 - Ingest Evidence`
  (`d46af04c-7cc7-4777-ad0e-dd049ad58a8b`)
- retained schedule: `CLI Control Tower - Weekly Founder Brief`
- retained ledger: `CLI Control Tower - Evidence Ledger`
  (`6491d754-0d52-4fa4-bae4-3de3d1e7a24f`)
- current token source: `form-access-token.txt`
- host-generated replacement token: `remediation/token-rotation/new-form-access-token.txt`
- stage report: `remediation/token-rotation/stage.json`
- final attestation: `remediation/token-rotation/attestation.json`

Resolve the schedule by exact title and confirm the stable ID against the Phase 04 and
latest reconciliation evidence before mutation. Never substitute a title-near match.

## Fresh approval and mutation budget

The rotation launcher requires the exact confirmation:

```text
ROTATE_PROCESIO_CONTROL_TOWER_ACCESS_TOKEN_V1
```

That approval authorizes only:

1. one desired-state edit of Ingest Evidence that changes the persisted expected token
   SHA-256 and no public variable ID, action topology, output, response contract, or
   unrelated value;
2. one desired-state edit of the existing weekly schedule that changes only its bound
   access-token input value;
3. two direct controlled Ingest runs: one with the old token to prove denial and one
   with the new token to prove acceptance;
4. at most three process instances total: old-token Ingest, new-token Ingest, and its
   awaited Normalizer child;
5. exactly one new ledger row for the pre-generated rotation evidence key;
6. host-side replacement of the protected local token file after platform proof;
7. host-side archival and invalidation of stale Phase 06 artifacts;
8. local snapshots, hashes, redacted evidence, and report updates under the run root.

It authorizes no form submission, webhook launch, schedule occurrence, connector call,
new retained resource, deletion of a platform resource, email, payment, external write,
or unrelated process run. There are no automatic retries.

## Secret-handling rules

1. The launcher generates the new token and writes it mode `0600` before the acting
   agent starts. The prompt contains only its path and SHA-256, never its value.
2. Read old and new token values only from their protected files. Never print them,
   interpolate them into a shell command, put them in a tool argument visible to the
   transcript, or write them into a report, log, screenshot, or ordinary artifact.
3. Build secret-bearing process-run and schedule-update payloads in mode-`0600`
   temporary files and pass them through `@file`. Delete them after the mutation or run
   outcome is reconciled.
4. Use `get-schedule --redact-process-inputs` for ordinary schedule inspection and
   post-write evidence. Raw schedule reads are forbidden in this remediation.
5. Evidence may contain token SHA-256 values, protected file paths, variable IDs, and
   `[REDACTED]`; it may not contain either clear token.
6. A lost response is an unknown mutation or run outcome. Reconcile by stable ID,
   update timestamp, evidence key, and instance window; do not repeat it blindly.
7. Redaction is cleanup, not revocation. The security outcome passes only after the old
   token is rejected and the replacement token succeeds.

## Required execution sequence

### 1. Snapshot and prove the starting state

- Read the old token from the protected source and verify its SHA-256 equals the frozen
  rotation metadata.
- Re-fetch Ingest and save a complete redacted before snapshot and digest.
- Read the schedule only through `get-schedule --redact-process-inputs`; save the
  redacted structure, stable ID, status, target process, recurrence, and digest.
- Confirm the schedule is enabled, targets the Weekly Orchestrator, and has exactly one
  access-token process-input row.
- Confirm the old token hash currently embedded in Ingest equals the metadata old hash.
- Record all pre-rotation Phase 06 files that the host must archive as stale.

### 2. Rotate the platform-side verifier and retained caller

- Edit Ingest once, changing only the expected access-token SHA-256 to the metadata new
  hash. Preserve all public input/output IDs, actions, edges, timeouts, error bindings,
  custom-response mapping, activation, and dependent form/subprocess mappings.
- Re-fetch and validate Ingest through backend and designer validation.
- Build a full schedule update payload in a protected temporary file without printing
  it. Change only the access-token input value, using the replacement token from the
  protected staging file. Preserve schedule ID, target, enabled state, cron,
  `Europe/Berlin` timezone, recurrence window, notifications, and every other input.
- Update once, then verify through `get-schedule --redact-process-inputs`. Evidence must
  show the correct variable ID and `[REDACTED]`, never the value.

### 3. Prove revocation and replacement

Use deterministic evidence key
`control-tower:token-rotation:<launcher-generated-uuid>` for both controlled tests.

1. Run Ingest exactly once with the old token and that key. It must return controlled
   denial before normalization or data-store write. Reconcile one Ingest instance and
   prove zero ledger rows for the key.
2. Run Ingest exactly once with the new token and the same key plus a benign accepted
   status payload. It must complete with its awaited Normalizer child and return an
   accepted decision. Prove exactly one ledger row for the key.
3. Re-read the ledger by exact key and prove uniqueness. Do not submit through the form
   or allow the schedule to fire for this test.
4. Revalidate Ingest and re-read the schedule through the redacted mode after both runs.

### 4. Prepare host finalization

- Delete every transient payload file containing either token.
- Sweep the complete run root for exact old-token and new-token byte sequences,
  excluding only the two designated protected token files. The launcher repeats this
  scan outside the acting agent and refuses promotion on any hit.
- Write the fixed stage report atomically. Do not replace `form-access-token.txt`, edit
  phase reports, or move Phase 06 artifacts; those are host-finalization operations.

## Stage report schema

```json
{
  "schema_version": 1,
  "project_id": "procesio-control-tower-v1",
  "remediation_id": "control-tower-token-rotation-v1",
  "stage": "05s-1-access-token-rotation",
  "status": "passed | blocked | unknown | failed",
  "summary": "factual, secret-free summary",
  "checks": [
    {"id": "fixed id", "passed": true, "evidence": "direct secret-free proof"}
  ],
  "budget_usage": {
    "process_edits": 1,
    "schedule_edits": 1,
    "process_runs": 2,
    "process_instances": 3,
    "ledger_rows_created": 1,
    "form_submissions": 0,
    "webhook_launches": 0
  },
  "token_rotation": {
    "old_sha256": "hex",
    "new_sha256": "hex",
    "evidence_key": "stable key",
    "ingest_process_id": "uuid",
    "schedule_id": "uuid",
    "old_token_instance_id": "uuid",
    "new_token_instance_ids": ["ingest uuid", "normalizer uuid"],
    "ledger_row_identity": "secret-free row id or evidence key"
  },
  "resources": [],
  "executions": [],
  "gaps": [],
  "unknown_outcomes": [],
  "next_stage_safe": true
}
```

Required checks, exactly once and in this order:

1. `exposure_acknowledged`
2. `before_snapshots_and_digests_saved`
3. `old_token_matches_current_ingest_hash`
4. `new_token_staged_only_in_protected_file`
5. `ingest_hash_updated_only`
6. `schedule_input_updated_only`
7. `ingest_and_schedule_valid`
8. `old_token_denied_without_write`
9. `new_token_accepted_and_row_unique`
10. `complete_execution_tree_within_budget`
11. `no_clear_token_in_agent_output_or_artifacts`
12. `phase06_artifacts_identified_as_stale`
13. `rotation_ready_for_host_finalization`
14. `no_unknown_outcomes`

A passing stage has all checks true, exact budget usage shown above, empty gaps and
unknown outcomes, and `next_stage_safe:true`. `passed_with_gap` is forbidden.

## Host finalization

After the report passes deterministic validation, the launcher:

1. scans the run root and the acting-agent log for both clear tokens;
2. atomically replaces `form-access-token.txt` with the staged replacement and enforces
   mode `0600`;
3. archives the currently promoted Phase 05 report and writes a new passed report that
   preserves functional remediation evidence, acknowledges the exposure, and records
   successful revocation and rotation;
4. archives every existing Phase 06 report, final report, deployment manifest, export,
   CSV, and prior status-normalization artifact, then removes those live paths because
   they describe the pre-rotation state;
5. writes `attestation.json` last with hashes, report lineage, exact budget, artifact
   inventory, and explicit statements that redaction did not erase the incident and
   the old credential is now rejected.

An interruption before the attestation remains safely resumable from immutable hashes.
The launcher never rebuilds or discards evidence automatically.

## Completion and next phase

Rotation completion does not itself complete the project. Run Phase 06 again from the
rotated state. The correct final scopes are:

- Phase 05: `passed`, with functional and security-remediation lineage;
- Phase 06: `passed` when its own audit/export checks pass;
- aggregate project: `passed_with_gap` only because Phase 03 retains the predeclared
  custom-connector fallback.
