# Form end-to-end verification

## Goal

Create or change a PROCESIO form and prove the user-visible behavior, process triggers, and runtime diagnostics—not merely the form DTO.

## Preconditions

- Identify workspace, form ID or create intent, public/private access, target URL, user roles, bound variables, triggered processes, and expected behavior per control/event.
- Ensure the `web` optional dependency/browser is installed and a dedicated saved session exists when authentication is required.
- Use isolated test data and avoid another person's active browser profile.

## Inspect

1. Fetch the form definition, custom URL, publication/access state, bound processes, and referenced data models.
2. Inventory tabs, controls, required fields, defaults, dynamic data, upload limits, and events (`onLoad`, submit, click, input, focus/blur, row/pagination events where present).
3. Read expected process input mappings and resulting user-visible states.

## Preview and approval

- Build/edit through the structured form DTO and inspect its dry-run output where available.
- Show access changes, event-triggered writes, notifications, and public exposure before saving or publishing.
- A screenshot mockup is not approval to create or publish a live form.

## Execute

- Save the form once, re-fetch it, then open the intended URL with the `web` tool.
- Exercise every changed control and event using stable labels/selectors rather than coordinates.
- Test normal, required/empty, invalid, boundary, and role/access paths relevant to the change.

## Verify

Pass only when all relevant layers agree:

1. Saved DTO matches intended controls, mappings, events, and access.
2. Browser interaction reaches the expected visible state with no page error, console error, failed request, or unexpected 4xx/5xx from the form's own calls.
3. Triggered processes create the expected instances and outputs/side effects.
4. Reload/back/navigation and repeated submission behavior are understood; duplicate submission is prevented or handled.
5. Private/public access behaves as designed in an appropriate session.

## Recovery and cleanup

Close only the browser/session started for verification. Remove test submissions and temporary fixtures where policy permits; never erase evidence needed to diagnose a failure. Revert publication/access immediately if exposure is broader than intended.

## Evidence

Return form ID and URL, controls/events covered, screenshots or DOM text where useful, browser diagnostics summary, process instance IDs, side-effect proof, and untested device/access paths.
