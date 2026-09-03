# Schedules and webhooks

## Goal

Create or change a time/event trigger and prove that its saved configuration launches the intended process exactly as designed.

## Preconditions

- Identify workspace, target process ID, trigger ID for edits, payload mapping, timezone, recurrence/event contract, activation state, concurrency/idempotency policy, and test window.
- Confirm the target process validates and can run with a controlled payload before attaching an automatic trigger.

## Inspect

1. Fetch existing schedule/webhook, target process, notifications, activation, timezone/recurrence, and recent related instances.
2. Check duplicate or overlapping triggers and downstream rate/concurrency limits.
3. For webhooks, inspect authentication/signature expectations, sample body, response behavior, replay handling, and secret exposure.

## Preview and approval

- Prefer creating schedules disabled and webhooks unattached/unshared until configuration review.
- Show next run times in an absolute timezone, target process, payload, notification recipients, and public endpoint exposure.
- Enabling, sharing, invoking, updating, or deleting a trigger is a mutation requiring the exact target to be approved.

## Execute

- Save the trigger once and re-fetch it.
- For a schedule, enable only for an agreed controlled occurrence or invoke the underlying process separately before enablement.
- For a webhook, launch with a signed/controlled sample using the intended content type and headers.
- Do not blind-retry a webhook request after an unknown response; reconcile by event/business ID.

## Verify

- Saved recurrence/timezone or webhook schema/auth settings match intent.
- Exactly one expected process instance is associated with the controlled event/window.
- Instance inputs, final status, outputs, notifications, and external side effects are correct.
- Duplicate delivery, missed run, clock/DST, overlap, and disabled-state behavior are covered where material.

## Recovery and cleanup

Disable the trigger immediately on unexpected firing, duplication, or payload mismatch. Preserve event IDs and instance evidence. Remove temporary schedules/webhooks and revoke test secrets/URLs after verification; never delete shared production triggers as cleanup without explicit approval.

## Evidence

Return trigger/process IDs, absolute test time or event ID, saved configuration summary, activation state, launched instance ID, side-effect proof, and recurrence/replay scenarios not yet exercised.
