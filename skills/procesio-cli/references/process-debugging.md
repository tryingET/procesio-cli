# Process debugging

## Goal

Explain a failed, silent, hanging, duplicated, or semantically wrong process outcome from runtime evidence, then apply the smallest verified correction if authorized.

## Preconditions

- Obtain environment, workspace, process ID, instance ID or failure window, expected outcome, and whether diagnosis is read-only.
- Confirm the credential profile can read the process and instances.
- Preserve failing inputs and evidence before editing or rerunning.

## Inspect

1. Fetch process design, input schema, activation, and dependencies.
2. Read the target instance status, variables, outputs, error details, timestamps, and child-instance references.
3. Inspect the flow graph and designer/runtime parity.
4. Follow the observed boundary: browser diagnostics for forms, SQL query for persistence, file inspection for documents, or API/custom-action test for integrations.
5. Consult the generated PROCESIO usage guide when a successful status produced no visible outcome.

## Preview and approval

Form a falsifiable root-cause statement tied to evidence. Before changing the process, show:

- failing node or boundary;
- input/state that triggers it;
- proposed minimal change;
- expected new observation;
- retry or duplicate-side-effect risk.

Diagnosis is not authorization to edit or rerun.

## Execute

- Add a focused reproduction or controlled input where possible.
- Change one cause, not several symptoms.
- Use native validation and a dry-run/DTO preview before save.
- Re-run only after reconciling whether the earlier attempt committed external effects.

## Verify

- The original reproduction now reaches the expected final status and output.
- A neighboring/edge input still behaves correctly.
- External side effects occur exactly once.
- Browser, database, file, or integration diagnostics are clean at the affected boundary.
- Static audit introduces no new secret, mapping, or error-handling issue.

## Recovery and cleanup

Keep the failed instance and compact diagnostic evidence. Remove temporary test resources, disable temporary schedules/webhooks, and restore the previous process version if the correction does not pass.

## Evidence

Report observed symptom, root cause, evidence chain, changed resource/version, before/after run IDs, direct proof, and remaining uncertainty. Distinguish confirmed cause from plausible hypothesis.
