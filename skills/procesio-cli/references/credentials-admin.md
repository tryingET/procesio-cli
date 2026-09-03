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
- Test a platform credential through its dedicated connection/test action when available.
- Verify granted scope by one permitted read and, when important, one expected denial outside scope.
- Re-fetch non-secret profile/credential metadata and confirm dependents still resolve.

## Recovery and cleanup

If a rotation fails, retain or restore the prior working credential until all dependents pass. Revoke temporary keys after testing. Do not remove the only administrative profile without a tested recovery path.

## Evidence

Return environment/workspace IDs, profile/credential name and type, storage backend category, readiness/auth test result, verified scope, dependents checked, and rotation/revocation status. Never include secret values.
