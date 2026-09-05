# Field trial: Evidence Status Normalizer

Operate against exactly this target:

- profile: `pure-awesomeness`
- environment: `Internal-PROD`
- workspace: `procesio-cli-pure-awesomeness`
- workspace ID: `dc28053d-f701-4880-99c2-7d973899d135`

The approved deliverable is one persistent, manually invoked process:

- title: `CLI Utility 01 - Evidence Status Normalizer`
- config: `examples/procesio/evidence-status-normalizer.process.json`
- representative payload: `examples/procesio/evidence-status-normalizer.sample-payload.json`

## Safety and scope

The operator approves exactly these mutations:

1. create one process with the exact title above, but only if no exact-title process already exists;
2. execute it exactly once with the committed sample payload;
3. keep the verified process in the workspace for later manual use.

Do not create a webhook, schedule, form, credential, data model, data store, document, file, connector, subprocess, or any other resource. Do not attach an autonomous trigger. Do not delete the process after a successful trial. Do not use `--force` to bypass validation.

If an exact-title process already exists, stop and report its ID instead of creating or editing anything. If a write or run times out, classify the outcome as unknown and reconcile by stable ID before any retry. Never launch a second representative execution merely to strengthen evidence.

## Required sequence

1. Load the `procesio-cli` skill and its `references/process-lifecycle.md` playbook.
2. Run `check-auth` with the exact profile, environment, and workspace ID. Hard stop unless `authenticated: true`.
3. Run `list-processes --search "CLI Utility 01 - Evidence Status Normalizer"` and prove that no exact-title process exists.
4. Run `process-create` with the committed config and `--dry-run`.
5. Inspect and report the resolved live `Node` action template ID and the exact property mappings for `Code`, `Timeout`, `Single Result`, and `Error`.
6. Require clean frontend/designer and backend validation. Do not bypass warnings or errors.
7. Create exactly one process from the same committed config. Capture its process ID.
8. Re-fetch the saved process and verify:
   - title is exact;
   - variables are input `status` (required JSON), output `normalized` (JSON), and output `script_error` (string);
   - graph is Start → Normalize evidence status → Stop;
   - `Timeout` is 60;
   - `Single Result` maps to `normalized`;
   - `Error` maps to `script_error`;
   - there are no webhooks, schedules, forms, credentials, subprocesses, or autonomous triggers.
9. Execute exactly once through `python scripts/run-agent.py procesio verify --run`, using the committed sample payload. Capture the instance ID.
10. Call `get-instance-output` directly with that instance ID and the process ID. Do not call `list-instances` unless the instance ID is missing or the run outcome is unknown.
11. Verify `script_error` is empty and `normalized` contains at least:

```json
{
  "decision": "ACCEPT_EVIDENCE",
  "complete": true,
  "gate5_evidence": true,
  "resumable": false,
  "status": "complete",
  "stop_reason": "gate5_series_passed",
  "completed_observations": 360,
  "remaining_observations": 0,
  "total_observations": 360
}
```

Also verify that `summary` contains `ACCEPT_EVIDENCE` and `next_action` is non-empty.

12. Run the non-executing process audit or use the audit output already included by the verification path. Report all findings.
13. Re-list processes and prove exactly one process with the exact title remains.
14. Save a non-secret report to `scratchpad/evidence-status-normalizer-result.json` containing the process ID, instance ID, validation results, resolved action ID, observed output, audit findings, and retained-resource status.

## Completion report

Return one compact report with:

- target profile, environment, workspace name, and workspace ID;
- process ID and instance ID;
- exact number of executions;
- frontend and backend validation verdicts;
- observed `normalized` and `script_error` outputs;
- proof of zero autonomous triggers and zero external dependencies;
- audit verdict;
- final exact-title process count;
- capabilities invoked;
- any discrepancy or unverified claim.

A successful result leaves the process in place. It does not imply that a webhook or form interface has been created; those are separate future approvals.
