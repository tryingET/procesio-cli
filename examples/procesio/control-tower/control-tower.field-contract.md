# PROCESIO Control Tower v1 — staged field contract

Build a retained, founder-facing **Automation Evidence & Founder Briefing Control Tower** in the exact workspace below. This is not a disposable demo. It is the operational home for future CLI field trials, skill-evaluation results, repository pulse data, resumable incidents, and founder briefings.

## Fixed target

- profile: `pure-awesomeness`
- environment: `Internal-PROD`
- workspace: `procesio-cli-pure-awesomeness`
- workspace ID: `dc28053d-f701-4880-99c2-7d973899d135`
- project manifest: `examples/procesio/control-tower/control-tower.project.json`
- seed evidence: `examples/procesio/control-tower/seed-evidence.json`
- connector source: `examples/procesio/control-tower/github-public-pulse.openapi.json`
- run root: `scratchpad/procesio-control-tower-v1`

The verified existing process `CLI Utility 01 - Evidence Status Normalizer`, ID `0528c553-8e17-4185-84cb-11068db503d8`, is an immutable dependency. Reuse it. Do not duplicate, edit, deactivate, or delete it.

## Governing operating contract

1. Load `procesio-cli` and progressively read the relevant references: operation contract, process lifecycle, process debugging, data verification, connector lifecycle, documents/files, forms E2E, schedules/webhooks, transport/environments, and credentials/admin.
2. Use repository capability discovery and exact `--help` output before guessing an action or argument. Prefer curated typed actions and DTO builders over raw API payloads.
3. Every client-backed call must carry the exact profile, environment, and workspace ID.
4. Resolve every existing or newly created resource by exact title and stable ID. An exact-title collision is not permission to edit it. Compare its saved design to the contract and either adopt an exact match or stop with a collision report.
5. Never blind-retry a timed-out write or process run. Treat the outcome as unknown, reconcile inventory or instances by stable ID and time window, and continue only after proving whether the operation committed.
6. Do not use `--force` to bypass a designer, backend, schema, concurrency, or validation gate.
7. Run each representative payload exactly once per acceptance claim. Use the returned instance ID for direct status/output reads; do not add `list-instances` when the ID is already known.
8. Bind every Node/Javascript/Python action's Error output. Node actions require a nonzero Timeout. Use Node `Single Result` or `List Result` for clean typed output.
9. Keep all generated configs, plans, local tokens, packages, downloaded files, exports, screenshots, and reports under the gitignored run root. Do not commit secrets or `.procesio` bundles.
10. Respect the resource caps in the project manifest. A useful missing feature is better than an unreviewed extra resource.
11. No email, payment, delete, database-external write, or arbitrary third-party mutation is authorized. GitHub operations are public read-only GETs only.
12. Do not modify tracked repository files during the field run. Report reusable CLI or skill defects for a later repository patch.

## Required phase report

At the end of each phase, write the exact JSON report path supplied by the launcher. The minimum schema is:

```json
{
  "schema_version": 1,
  "project_id": "procesio-control-tower-v1",
  "phase": "<phase id>",
  "status": "passed | passed_with_gap | blocked | unknown | failed",
  "summary": "<short factual summary>",
  "resources": [{"kind":"process","name":"...","id":"...","state":"created|adopted|verified|deleted"}],
  "executions": [{"process_id":"...","instance_id":"...","status":50,"purpose":"..."}],
  "checks": [{"id":"...","passed":true,"evidence":"..."}],
  "gaps": [],
  "unknown_outcomes": [],
  "next_phase_safe": true
}
```

`next_phase_safe` may be true only when there is no unreconciled write/run outcome, no unexplained duplicate, and no failed required acceptance condition. A `passed_with_gap` result is allowed only for the custom-connector stretch path when the documented Call API fallback is fully verified.

---

# Phase 01 — discovery and immutable blueprint

**Mutation allowance: none.**

1. Run `check-auth`. Hard stop unless `authenticated:true`.
2. Confirm the workspace name-to-ID mapping.
3. Inventory exact-title collisions for every resource in the project manifest: processes, data models, data stores, custom actions/connectors, credentials, documents, forms, schedules, and webhooks.
4. Re-fetch and non-executingly validate/audit the existing Evidence Status Normalizer. Confirm its title, process ID, variables, Node action, no trigger, and no external dependency.
5. Discover the exact live action templates and property labels/IDs needed for:
   - Node;
   - Call Subprocess;
   - Decisional and Join;
   - For Each;
   - native data-store row read/add/update;
   - custom connector action or unversioned Call API;
   - Generate Document;
   - any form RUN_PROCESS mapping.
6. Inspect the data model, data store, document, form, schedule, webhook, transport, and connector-builder schemas/help.
7. Create a local immutable blueprint at `scratchpad/procesio-control-tower-v1/blueprint.json` containing exact intended names, discovered action IDs/property IDs, dependency order, expected mutations, rollback targets, and verification method.
8. Generate a random 128-bit form access token locally. Store the clear token only at `scratchpad/procesio-control-tower-v1/form-access-token.txt`, mode `0600`. Store its SHA-256 hash in the blueprint. Never print the clear token in model output or logs.
9. Write the phase report. `next_phase_safe:true` requires zero collisions or only exact-design matches that are safe to adopt.

# Phase 02 — evidence model, ledger, and idempotent ingest

**Authorized retained mutations:** one data model, one data store, one process.

## Data model

Create `CLI Control Tower - Evidence Record` with every attribute listed in the project manifest **in the initial create**. Do not add attributes later. Re-fetch and verify names, types, required flags, and stable attribute IDs.

## Data store

Create `CLI Control Tower - Evidence Ledger` from that data model. Use `Evidence Key` as the primary key. Provisioning may take several minutes; a client-side timeout is an unknown result, so inventory before retrying.

Verify:

- metadata and backing data model;
- exactly one primary-key column;
- add/read/update/filter/sort behavior using one temporary controlled row;
- delete only that temporary row after evidence capture;
- neighboring rows remain untouched.

## Ingest process

Create `CLI Control Tower 01 - Ingest Evidence` with inputs sufficient for authenticated CLI, form, and webhook callers:

- `evidence_key` required string;
- `source` required string;
- `title` required string;
- `kind` string;
- `owner` string;
- `artifact_reference` string;
- `status_json` required string;
- `access_token` string.

Outputs must include `record`, `decision`, `summary`, `next_action`, `duplicate`, `response`, and one or more bound script/action error variables.

Required behavior:

1. Validate the access token by hashing the input and comparing it to the locally generated hash stored in the process definition. An invalid token returns a controlled denial and writes no row.
2. Parse `status_json` deterministically. Invalid JSON returns a controlled error and writes no row.
3. Call the immutable Evidence Status Normalizer by stable process ID. Map the parsed status through a **plain parent variable**.
4. Derive severity deterministically:
   - `ACCEPT_EVIDENCE` → `success`;
   - `RESUME_CHECKPOINT` → `attention`;
   - `INVESTIGATE_GATE` → `blocked`;
   - `DIAGNOSE_INFRASTRUCTURE` → `incident`;
   - otherwise `review`.
5. Query the ledger by exact `Evidence Key` before writing.
6. If absent, add one row. If present, update that row rather than inserting a duplicate. Converge create/update branches through Join.
7. Preserve Created At on update and set Updated At on every accepted write.
8. Return a structured response and configure the process custom response to that response variable for synchronous form callers.
9. Bind Node Error outputs and route operational action errors to a controlled handler.
10. No webhook, form, schedule, credential, file, or external API dependency is attached in this phase.

Dry-run, inspect the resolved graph/mappings, require clean designer and backend validation, create once, re-fetch, audit, and run exactly these two tests:

- valid token + a unique test key → one row, expected normalized decision;
- invalid token + a different key → controlled denial, zero row.

Delete only the valid temporary test row. Write the phase report with process, model, store, and instance IDs.

# Phase 03 — GitHub public connector and repository pulse

**Authorized retained mutations:** one custom connector/custom-action package, zero or one non-secret credential, one process.

## Preferred path: custom connector

Use the `connector-builder` agent and `github-public-pulse.openapi.json` to perform gather → plan → generate → compile. Review the plan before generation. The package may expose only:

- `GetRepository`;
- `GetCommit`.

There must be no POST, PUT, PATCH, or DELETE operation and no secret embedded in source, package metadata, logs, or outputs.

Retain the build ID, package name/version, digest, and generated source under the run root. Install once in the target workspace. Test:

1. successful public read of `tryingET/procesio-cli` and `main`;
2. expected 404 using a clearly nonexistent repository, surfaced as a useful stable connector error.

Allow at most two generation/compile attempts and one installation attempt. Feed concrete compiler/runtime evidence into only the smallest responsible correction.

## Documented fallback

When connector generation or installation is unavailable for a concrete platform/tooling reason, use the unversioned live `Call API` action. Create at most one REST API credential named `CLI Control Tower - GitHub Public API` only when required. It must contain no secret; base URL and public headers only. Record `status:passed_with_gap`, the exact connector gap, and the verified fallback.

## Repository Pulse process

Create `CLI Control Tower 02 - Repository Pulse`.

Required behavior:

1. Inputs default to owner `tryingET`, repo `procesio-cli`, ref `main`.
2. Call the custom connector or verified fallback to retrieve repository and commit metadata.
3. Bind all action error outputs and handle provider errors explicitly.
4. Build an evidence status object describing current commit, repository URL, stars/forks/open issues, last push, and whether the public read succeeded.
5. Call `CLI Control Tower 01 - Ingest Evidence` synchronously with a deterministic key such as `github:tryingET/procesio-cli:<sha>` and the valid local access token.
6. Output repository pulse, ingested record, and stable errors.

Dry-run, validate, create once, re-fetch, audit, run one success, read the exact instance output, and verify exactly one matching ledger row. Do not test GitHub writes.

# Phase 04 — founder brief, orchestrator, file proof, and weekly schedule

**Authorized retained mutations:** one document template, two processes, one schedule.

## Founder Brief document

Create `CLI Control Tower - Founder Brief`, A4 portrait, polished HTML suitable for a founder. It must visibly communicate:

- project purpose and generated-at time;
- KPI cards: total evidence, accepted, resumable, blocked, incidents;
- current repository pulse and commit;
- a repeating table of recent evidence rows;
- top next actions;
- evidence integrity note and workspace scope.

Use the fresh Evidence Record data model and a repeating table over a typed list. All document attributes must already exist from the initial model create. Apply a restrained, professional visual system; do not depend on remote images.

## Founder Brief process

Create `CLI Control Tower 03 - Founder Brief`.

Required behavior:

1. Read ledger rows with paging, filtering, and descending Updated At sort.
2. Use a clean typed list output. Exercise For Each for one meaningful per-record operation, then aggregate KPI values deterministically.
3. Generate the document through `Generate Document`, mapping scalar variables and the full typed evidence list.
4. Produce a PDF File output and an HTML/summary output when supported.
5. Bind Error outputs and fail visibly on document-generation errors.
6. Verify the generated file by direct download: nonzero bytes, PDF signature, and extractable expected text including `PROCESIO Control Tower` and at least one real evidence title.

## Weekly Orchestrator

Create `CLI Control Tower 04 - Weekly Orchestrator`.

It must synchronously call Repository Pulse and then Founder Brief, returning the repository result, brief file, summary, and errors. Use awaited Call Subprocess, not fire-and-forget, because the schedule requires proof of both outcomes.

## Seed and prove

Use the valid token and the records in `seed-evidence.json` to ingest the real historical evidence. Each evidence key may produce at most one row. Verify the expected decisions `ACCEPT_EVIDENCE`, `RESUME_CHECKPOINT`, and `INVESTIGATE_GATE` in the ledger.

Run the Weekly Orchestrator exactly once, inspect both child outcomes, download the PDF, and audit all four Control Tower processes.

## Schedule

1. Preview `0 9 * * 1` in `Europe/Berlin` with the cron validator and record upcoming absolute occurrences.
2. Create `CLI Control Tower - Weekly Founder Brief` **disabled** and target the Weekly Orchestrator.
3. Re-fetch the schedule and verify target, recurrence, timezone, payload, and notifications.
4. Only after the manual orchestrator run and PDF proof pass, enable the schedule.
5. Confirm it is enabled and that there is exactly one schedule for the orchestrator.
6. Do not wait for or force an actual scheduled occurrence during the field run.

# Phase 05 — polished Mission Control form and temporary webhook drill

**Authorized retained mutations:** one form. **Authorized temporary mutations:** one webhook that must be removed before phase completion.

## Mission Control form

Create and publish `CLI Control Tower - Mission Control` as a polished, founder-demo-quality form. It must remain genuinely useful for entering future evidence.

Required UX:

- a clear hero heading and concise explanation;
- tabs or sections for `Submit Evidence`, `Decision`, and `How It Works`;
- fields for access token, evidence key, source, title, kind, owner, artifact reference, and status JSON;
- client-side JSON validity feedback and a live character counter implemented safely in the parent document realm;
- synchronous RUN_PROCESS event to `CLI Control Tower 01 - Ingest Evidence`;
- result fields for decision, severity/summary, next action, duplicate/update state, and controlled errors;
- an accessible restrained theme, responsive columns, and no broken remote image;
- no secret default value and no clear access token embedded in form code or config.

Perform real-browser verification with the repository `web` tool:

1. load the published URL;
2. confirm there are no console errors, page errors, failed requests, or bad responses before interaction;
3. enter the valid local token and one unique paused/resumable evidence payload;
4. submit once;
5. verify the returned decision is `RESUME_CHECKPOINT` and next action is visible;
6. verify exactly one ledger row with the form evidence key;
7. capture a screenshot under the run root and record browser diagnostics.

## Temporary webhook drill

Create `CLI Control Tower - Intake Drill` from a body sample that maps to the ingest inputs. Attach it to Ingest Evidence, validate the process, activate only as required for the controlled launch, and invoke it once with:

- valid access token;
- unique evidence key;
- a `blocked` status payload expected to normalize to `INVESTIGATE_GATE`.

Because webhook launch is asynchronous, reconcile the resulting process instance and ledger row by exact evidence key and time window. Do not blindly resend on an unknown response.

After proof:

1. detach the webhook from the process;
2. revalidate and re-audit the process;
3. delete the webhook;
4. prove zero exact-title webhooks remain and no public write endpoint is retained.

The form remains; the webhook does not.

# Phase 06 — export, acceptance audit, and retained deployment

**No new feature resources.** Export/download artifacts are allowed under the run root.

1. Re-inventory every exact resource title and stable ID. Prove no duplicates and no resources beyond the manifest caps.
2. Re-fetch and validate all retained processes, the form, document, data model, data store, custom action/connector or fallback credential, and schedule.
3. Verify the existing Evidence Status Normalizer is unchanged.
4. Verify the ledger contains at least four useful rows and includes all three required decision classes.
5. Run the Weekly Orchestrator one final time only when the earlier orchestrator outcome is unavailable or failed. Do not create a redundant second acceptance run merely for more evidence.
6. Confirm the schedule is enabled, has the intended cron/timezone, and no second schedule targets the orchestrator.
7. Confirm final webhooks with the temporary title equal zero.
8. Export the selected retained project resources to `scratchpad/procesio-control-tower-v1/export/`. Exclude credential secrets. Record file name, byte size, SHA-256 digest, selected resources, and exclusions. Do not import it anywhere.
9. Export the Evidence Ledger to CSV, download it, and verify headers, exact row count, unique Evidence Keys, and representative values.
10. Save a sanitized deployment manifest at `scratchpad/procesio-control-tower-v1/deployment.json` with all resource IDs, URLs safe to retain, connector version, schedule ID/state, form URL, latest PDF file metadata, export digest, and verified decisions. Do not include access tokens or credential secrets.
11. Save `scratchpad/procesio-control-tower-v1/final-report.json` with:
    - all phase verdicts;
    - exact capabilities invoked;
    - resource inventory;
    - process and instance IDs;
    - browser proof;
    - ledger proof;
    - document/file proof;
    - connector success/error proof or fallback gap;
    - schedule state and upcoming occurrences;
    - export/CSV digests;
    - platform execution count and approximate runtime consumed during build;
    - retained resources and temporary resources removed;
    - discrepancies, unknowns, and manual checks.
12. The final phase passes only when all required core features are directly verified and there is no unknown mutation outcome. The custom connector may be the sole `passed_with_gap` feature when the verified Call API fallback is used.

## Final completion message

Return a compact founder-readable summary plus the path to `final-report.json`. State clearly:

- what is now useful in daily work;
- the form URL and how the local access token is obtained;
- the weekly schedule and its next occurrences;
- the latest founder brief file proof;
- the evidence ledger row count and decision coverage;
- custom connector or fallback mode;
- exact retained resource counts;
- zero retained anonymous webhooks;
- any remaining gap.
