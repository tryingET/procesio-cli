# Schedules and webhooks

## Goal

Create or change a time/event trigger and prove that its saved configuration launches the intended process exactly as designed.

## Preconditions

- Identify workspace, target process ID, trigger ID for edits, payload mapping, timezone, recurrence/event contract, activation state, concurrency/idempotency policy, and test window.
- Confirm the target process validates and can run with a controlled payload before attaching an automatic trigger.
- For a webhook, determine the live payload-binding granularity before designing the target process. A generated webhook body is a typed model object; do not assume the platform can fan its fields directly into several primitive process inputs.

## Inspect

1. Fetch existing schedule/webhook, target process, notifications, activation, timezone/recurrence, and recent related instances.
2. Check duplicate or overlapping triggers and downstream rate/concurrency limits.
3. For webhooks, inspect authentication/signature expectations, sample body, generated body model and attribute IDs, response behavior, replay handling, secret exposure, and the exact `WebhookVariableDto`/attachment shape.
4. Inspect the complete process tree the trigger can create. One delivery may create a trigger-target instance plus awaited child and nested instances.

## Preview and approval

- Prefer creating schedules disabled and webhooks unattached/unshared until configuration review.
- Show next run times in an absolute timezone, target process, payload, notification recipients, and public endpoint exposure.
- Enabling, sharing, invoking, updating, or deleting a trigger is a mutation requiring the exact target to be approved.
- Predeclare one stable event/business key, one launch window, the maximum trigger deliveries, and the full parent/child instance budget.

## Execute

- Save the trigger once and re-fetch it.
- For a schedule, enable only for an agreed controlled occurrence or invoke the underlying process separately before enablement.
- For a webhook, launch with a signed/controlled sample using the intended content type and headers.
- Bind a webhook's generated body to one compatible model-typed process input. When the retained target exposes primitive inputs, use a bounded adapter process that accepts the whole body, extracts attributes deterministically, and calls the retained target through plain variables. Do not repeat a failed per-field primitive mapping.
- Keep a test adapter temporary unless it is part of the reviewed architecture. Bind scripting Error outputs, use nonzero timeouts, and preserve the retained target's public variable IDs.
- Do not blind-retry a webhook request after an unknown response; reconcile by event/business ID and time window.

## Verify

- Saved recurrence/timezone or webhook schema/auth settings match intent.
- Exactly one expected delivery is associated with the controlled event/window.
- The complete trigger-target/child instance tree is reconciled; inputs, final statuses, outputs, notifications, and external side effects are correct.
- For a webhook, prove the model object reached the intended model-typed input or adapter, the extracted primitive values are correct, and the final business-key side effect exists exactly once. An attached DTO plus a never-started instance is not a passing mapping test.
- Duplicate delivery, missed run, clock/DST, overlap, and disabled-state behavior are covered where material.

## Recovery and cleanup

Disable the trigger immediately on unexpected firing, duplication, or payload mismatch. Preserve event IDs and instance evidence. Remove temporary schedules/webhooks and revoke test secrets/URLs after verification; never delete shared production triggers as cleanup without explicit approval.

For a temporary webhook adapter, detach the webhook first, revalidate retained processes, delete the webhook and adapter, then prove zero matching public endpoints, adapter processes, and live references to the generated webhook model remain.

## Evidence

Return trigger/process IDs, generated webhook model and relevant attribute IDs, absolute test time or event ID, saved configuration summary, activation state, delivery count, full parent/child instance tree, side-effect proof by stable business key, adapter cleanup, and recurrence/replay scenarios not yet exercised.
