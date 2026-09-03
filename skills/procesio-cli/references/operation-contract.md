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

## Retry classification

| Result | Retry rule |
|---|---|
| Explicit validation failure before send | Correct input; safe to retry |
| Read-only request failed before response | Retry with bounded backoff if transient |
| Write returned a stable error proving no commit | Correct cause; retry once appropriate |
| Write timed out, connection reset, or response was lost | Unknown outcome: re-read first; never blind retry |
| Write succeeded but verification failed | Investigate state; do not repeat mutation as a repair guess |

## Proof standard

Select evidence at the same boundary the user cares about:

- API/DTO state for configuration outcomes;
- runtime instance for process outcomes;
- browser interaction plus diagnostics for form outcomes;
- database query for persisted data outcomes;
- downloaded file inspection for document outcomes;
- installed package plus action invocation for connector outcomes.

Keep the evidence small: IDs, status, relevant fields, output digest/path, and diagnostics. Avoid dumping secrets or entire payloads when a few fields prove the result.
