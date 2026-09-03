# Process lifecycle

## Goal

Create or change one PROCESIO process and prove both its saved design and representative runtime behavior.

## Preconditions

- Identify environment, workspace ID, credential profile, process ID for edits, representative input, and expected outputs/side effects.
- Run readiness/auth checks and resolve the process by stable ID.
- Use the `procesio` agent for a full build-and-test outcome. Use a narrow `procesio` tool action only for one explicit read or edit.

## Inspect

1. Read agent guidance for the current build/test doctrine.
2. Fetch the existing process and input payload shape when editing or running.
3. Inspect dependencies: data models, credentials, child processes, documents, webhooks, schedules, and custom actions.
4. Record activation state and a compact before-state.

## Preview and approval

- Build or edit through the structured process DTO path; use dry-run/validation before save when available.
- Inspect the generated action graph, mappings, branches, error ports, and output variables.
- Treat create, edit, activation, run, duplicate, import, and delete as mutations. Cross the MCP confirmation boundary only after the target and blast radius are explicit.

## Execute

- Save one coherent process version.
- Validate it at the source platform.
- Apply layout or action-name cleanup only when it does not change behavior.
- Run once with the representative payload. Do not blind-retry a timed-out run; reconcile instances first.

## Verify

Minimum proof:

1. Re-fetch the process and compare the saved design with the intended DTO/graph.
2. Run the `procesio` agent verification path with `--run` where safe.
3. Read the real instance status, inputs, outputs, and error details.
4. Verify external effects at their boundary: database row, generated file, API result, email sink, or child instance.
5. Run the static audit for secrets, missing error handling, inefficient patterns, and designer/runtime mismatch.

Validation alone does not pass this playbook.

## Recovery and cleanup

- Validation failure: correct the DTO or mappings before another save.
- Unknown run outcome: list/reconcile instances by process and time before rerunning.
- Failed test mutation: restore the prior exported/saved configuration or create a follow-up corrective edit; do not delete evidence.
- Deactivate test triggers and remove temporary fixtures created by the run.

## Evidence

Return environment/workspace/process/instance IDs, validation result, runtime status, relevant outputs or side-effect proof, audit findings, and any manual production check still open.
