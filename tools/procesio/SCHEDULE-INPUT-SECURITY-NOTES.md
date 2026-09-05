# Schedule process-input security

This note records a live-observed security property of the PROCESIO schedule API.
It belongs beside the curated schedule handler because it describes the wire and
storage behavior of `/api/Schedules`, not one project's workflow.

## Observed contract

Verified in the `Internal-PROD` environment on 2026-09-05:

- values supplied in a schedule's `processInputs` are persisted as part of the
  schedule definition;
- `GET /api/Schedules/{scheduleId}` returns those values without masking them;
- saving a schedule GET response, debug dump, transcript, screenshot, or report can
  therefore disclose any token, password, API key, or other secret placed there;
- redacting a local artifact after the read does not undo disclosure to an already
  captured transcript or external log;
- a claim that the clear value exists “only in a local protected file” is false while
  the same value remains in a readable schedule definition.

The current curated `get-schedule` action preserves the raw API DTO for exact
round-tripping and does not automatically redact `processInputs`. The generic request
surface can expose the same values. Treat both as secret-bearing reads whenever a
schedule has non-empty process inputs.

## Required handling

1. Prefer a target process that resolves authentication through a named credential,
   secret store, or other runtime reference instead of receiving a long-lived secret
   as a literal schedule input.
2. When a literal secret is temporarily unavoidable, use a dedicated least-privilege,
   rotatable value. Do not reuse a personal or broad administrative credential.
3. Pass a secret-bearing create/update payload through a protected `@file`, not inline
   JSON that may enter shell history, process listings, or logs. Delete the temporary
   file only after the write outcome is reconciled.
4. Restrict `Schedule.Read` and artifact access to principals that may read the secret.
5. Never print or persist a raw schedule DTO in ordinary evidence. Record the variable
   identifiers and replace each sensitive `processInputs[].value` with `[REDACTED]`.
6. After any accidental transcript, log, screenshot, or artifact exposure, treat the
   value as disclosed and rotate it. Update every dependent hash, schedule input, and
   protected local source as one reconciled change.
7. Verify rotation by proving the old value is rejected, the new value succeeds, the
   schedule contains only the new value, and no retained evidence contains either
   clear value.

## Evidence boundary

A safe schedule-security claim needs all relevant storage boundaries:

- protected local source and its permissions;
- process definition or credential reference;
- schedule `processInputs` as a redacted structural summary;
- transcripts, logs, screenshots, exports, deployment manifests, and saved API reads;
- rotation or revocation proof after exposure.

A clean local-file sweep alone does not prove that the platform-side schedule copy or
an external transcript is clean.
