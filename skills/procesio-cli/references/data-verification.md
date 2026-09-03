# Data and side-effect verification

## Goal

Change a PROCESIO data model or data-processing workflow and prove the resulting schema, query result, database state, or workbook content at the real storage boundary.

## Preconditions

- Identify workspace, data-model/process ID, target database or file, credential profile, environment, expected rows/fields, transaction/idempotency behavior, and safe test key.
- For SQL Server tuning, load `sql-server-optimizer`; this playbook owns platform execution and end-to-end proof.
- Confirm database/query tools are configured without exposing credentials.

## Inspect

1. Fetch the data model and process mappings.
2. Inspect target table/file schema, keys, constraints, indexes where relevant, and existing row for the test business key.
3. Record before-state narrowly enough to prove the change without copying sensitive datasets.
4. For workbooks, list sheets and expected ranges/formulas before transformation.

## Preview and approval

- Preview data-model/process DTO changes and SQL/action parameter mappings.
- Show DDL/DML, overwrite, delete, bulk, or export effects and rollback strategy.
- A process run that writes data is a mutation even when the CLI action name is `run-process`.

## Execute

- Save one schema/mapping change and re-fetch it.
- Run with a unique controlled business/idempotency key.
- For an unknown database outcome, query by that key before retrying.
- Keep deterministic extraction/parsing separate from model interpretation.

## Verify

- Re-fetch the PROCESIO data model and validate the process.
- Query SQL Server/MySQL or inspect the downloaded workbook/file directly.
- Verify exact row count, key, values/types, null handling, duplicates, and transaction outcome.
- For update/delete, prove both intended changes and protected neighboring data.
- Inspect process instance outputs and errors so storage proof and orchestration proof agree.

## Recovery and cleanup

Use an explicit test key and reversible transaction/fixture where possible. Remove only rows/files created by the test after evidence capture. For schema changes, use the reviewed rollback/migration path rather than ad-hoc destructive reversal.

## Evidence

Return model/process/instance IDs, sanitized before/after query or workbook facts, affected row/file counts, business key, duplicate/idempotency result, and any production-scale/concurrency check not performed.
