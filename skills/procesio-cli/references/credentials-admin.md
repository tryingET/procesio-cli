# Credentials and workspace administration

## Goal

Configure or diagnose credential profiles, workspace scope, users, API keys, or platform credentials without placing secrets in repository files, logs, evidence, or broad unintended scope.

## Preconditions

- Identify installation/environment, credential type, intended workspace/account scope, least-privilege role, profile name, and requested administrative outcome.
- Determine whether the machine has an OS keyring or needs an approved headless backend.
- Never ask the user to paste a reusable secret into a tracked file or ordinary chat evidence.

## Inspect

1. List profiles and readiness metadata only; do not read or echo secret values.
2. Read environment/workspace inventory with an existing least-privilege profile where possible.
3. Distinguish user/password session reach from workspace-scoped API-key reach.
4. For platform credentials, inspect template, non-secret fields, dependent resources, and current test status.

### Authentication hard stop

- `mode: apikey` or `mode: userpass` reports the stored profile type only. It is not evidence that authentication worked.
- If `check-auth` returns `authenticated: false`, or its probe returns `401`/`403`, stop all remote PROCESIO calls. Do not try alternate endpoints; they cannot confirm the workspace while the same credential is rejected.
- The only allowed follow-up diagnostics are local and non-secret: `show-credential`, `list-credentials`, and `show-environment`.
- Do not inspect credential-store internals, dump environment variables, print commands containing secrets, or search source code for a way around the failed check.
- If the non-secret metadata is correct, ask the operator to recreate or re-enter the API key in this exact order: **API key NAME**, then **API key VALUE**, for the intended workspace. Retry `check-auth` before any other API call.
- Until a server response succeeds, report the requested workspace as **configured but not confirmed**.

## Preview and approval

- Show profile name/type/scope and storage backend—not secret content.
- For user/role/API-key/credential creation, update, default switch, removal, or rotation, state affected workspace and dependents.
- Removing or replacing a credential can break many processes; inventory references first.

## Execute

- Use secure prompt/keyring-backed actions for secret capture.
- Store environment/profile binding separately from the secret.
- Make one narrow administrative change.
- Do not print the command with the secret substituted, and redact provider responses.

## Verify

- Run the cheapest read-only auth/health check with the named profile and intended workspace.
- Continue only when the result explicitly says `authenticated: true`; a status code or profile mode must not be reinterpreted as success.
- Test a platform credential through its dedicated connection/test action when available.
- Verify granted scope by one permitted read and, when important, one expected denial outside scope.
- Re-fetch non-secret profile/credential metadata and confirm dependents still resolve.

## Recovery and cleanup

If a rotation fails, retain or restore the prior working credential until all dependents pass. Revoke temporary keys after testing. Do not remove the only administrative profile without a tested recovery path.

For a newly created disposable profile that has never authenticated, remove the local profile, create a fresh key while the intended workspace is selected, store the new name/value through the secure prompt, and repeat only `check-auth`.

## Evidence

Return environment/workspace IDs, profile/credential name and type, storage backend category, readiness/auth test result, verified scope, dependents checked, and rotation/revocation status. Never include secret values.
