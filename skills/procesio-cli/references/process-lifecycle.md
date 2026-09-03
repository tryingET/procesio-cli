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
- If the create DTO is active by default, state that explicitly. Confirm whether any attached webhook, schedule, form event, or other trigger could launch it autonomously. An active process with no trigger still requires approval to run, but it has no autonomous launch path.

## Execute

- Save one coherent process version.
- Validate it at the source platform.
- Apply layout or action-name cleanup only when it does not change behavior.
- Execute the representative payload **exactly once**. Prefer the `procesio` agent verification path with `--run` because it validates, audits parity, runs, and reads instance status in one operation.
- Do not also call `run-process` before or after `verify --run` merely to obtain the same proof. If a representative run was already launched, inspect that instance directly and run non-executing validation/audit checks instead.
- Do not blind-retry a timed-out run; reconcile instances first.

## Verify

Minimum proof:

1. Re-fetch the process and compare the saved design with the intended DTO/graph.
2. Use one execution path only:
   - preferred: `procesio` agent `verify --run`, then use the returned instance ID for output inspection; or
   - direct `run-process` once, followed by explicit instance-status/output reads and a non-running audit.
3. Read the real instance status, inputs, outputs, and error details. Status alone is not proof of the expected output value.
4. Verify external effects at their boundary: database row, generated file, API result, email sink, or child instance.
5. Run the static audit for secrets, missing error handling, inefficient patterns, and designer/runtime mismatch.

Validation alone does not pass this playbook. Two successful executions are not stronger evidence when one representative execution and direct output inspection prove the same claim.

## Recovery and cleanup

- Validation failure: correct the DTO or mappings before another save.
- Unknown run outcome: list/reconcile instances by process and time before rerunning.
- Failed test mutation: restore the prior exported/saved configuration or create a follow-up corrective edit; do not delete evidence before recording the failure.
- Deactivate test triggers and remove temporary fixtures created by the run.
- For a disposable smoke test, delete the process only after its process ID, instance ID, validation result, runtime status, and expected output have been captured. Re-list the workspace to prove cleanup.

## Evidence

Return environment/workspace/process/instance IDs, validation result, runtime status, relevant outputs or side-effect proof, audit findings, cleanup result, and any manual production check still open.
