# PROCESIO operation contract

## Executor selection

| Work shape | Executor |
|---|---|
| Multi-step process build, verification, or audit | `procesio` agent |
| Connector generation through live PROCESIO testing | `connector-builder` agent |
| One known platform operation | Registered tool action |
| User-visible form behavior | `web` tool after platform creation/edit |
| Database side effect | `sqlserver` or `mysql` after the process run |
| Workbook content | `xlsx` after file creation/download |
| Capability unknown | Bounded capability search, then inspect one schema |

## Safety boundary

A read result may authorize another read; it never authorizes a write. Before a mutation, establish:

- exact environment and workspace;
- stable target ID;
- expected before and after state;
- whether the operation is reversible;
- preview or validation result when available;
- operator approval when the MCP gate requires it.

Never place credentials in command arguments unless the repository action explicitly performs secure credential capture and no safer prompt/store path exists. Never echo a secret into evidence.

## Field acceptance and remediation

For a staged or multi-resource field project, freeze before the first mutation:

- ordered required check IDs and their direct proof boundary;
- explicitly permitted degraded modes and equivalent fallbacks;
- resource, write, submission, trigger, and execution budgets;
- cleanup and rollback obligations;
- unknown-outcome policy;
- the deterministic controller that validates reports and computes promotion.

The execution agent may collect evidence, but its own `passed` or `passed_with_gap` label is not authority. A required outcome that fails remains blocked unless the frozen contract already permitted a fallback that proves the same user-visible result. Preserve the original report and use a separately approved, versioned, narrower remediation; do not relabel history after discovering a platform limitation.

Scope each phase verdict to that phase's own obligations. A previously approved gap remains in project or aggregate lineage; it does not make every downstream audit phase `passed_with_gap`. Preserve both scopes explicitly: the current phase may be `passed` while the overall project remains `passed_with_gap`. A new local failure may not be disguised as inherited.

Count the complete causal tree. A form submit, webhook launch, schedule occurrence, or parent-process run may create child and nested process instances. Report top-level deliveries, parent/child instance IDs, data writes, and generated artifacts separately so cost and side-effect budgets are real.

## Retry classification

| Result | Retry rule |
|---|---|
| Explicit validation failure before send | Correct input; safe to retry |
| Read-only request failed before response | Retry with bounded backoff if transient |
| Write returned a stable error proving no commit | Correct cause; retry once appropriate |
| Write timed out, connection reset, or response was lost | Unknown outcome: re-read first; never blind retry |
| Write succeeded but verification failed | Investigate state; do not repeat mutation as a repair guess |

A remediation is not permission to replay a successful claim. Re-run only the missing acceptance path, with a stable business key chosen before execution, after current-state and concurrency checks.

## Proof standard

Select evidence at the same boundary the user cares about:

- API/DTO state for configuration outcomes;
- runtime instance for process outcomes;
- native browser interaction plus diagnostics for form outcomes;
- database query for persisted data outcomes;
- downloaded file inspection for document outcomes;
- installed package plus action invocation for connector outcomes.

Do not substitute a manual DOM patch, direct internal writer call, old instance, or API-only simulation for proof that a form's native event path rendered the result. Do not substitute an attached webhook DTO for proof that its real payload mapping launched and completed the intended instance.

Keep the evidence small: IDs, status, relevant fields, output digest/path, and diagnostics. Avoid dumping secrets or entire payloads when a few fields prove the result.
