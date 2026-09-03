# SQL Server context collection

Collect only what can change the recommendation.

## Minimum context

- exact query/object definition;
- SQL Server version and database compatibility level;
- relevant table columns and data types;
- primary/foreign/unique keys;
- current indexes including key order, includes, filters, and usage where available;
- representative row counts and parameter values;
- actual execution plan and `STATISTICS IO/TIME` when safe;
- concurrency symptom: slow alone, blocked, blocking others, or intermittent.

## Agentic path

Use the registered `sqlserver` tool for read-only metadata and measurements when a configured profile exists. Ask before executing a workload that may be expensive or touch production. Do not request credentials in chat or put them in SQL files.

## User-provided path

The bundled scripts are read-only metadata exporters:

- `scripts/export-tables.sql`
- `scripts/export-indexes.sql`
- `scripts/export-procs-and-functions.sql`

Request only the relevant outputs. Redact literals, customer data, and secret-bearing definitions. An estimated plan is useful for compile-time shape; an actual plan is needed for actual rows and runtime warnings.

## Baseline discipline

Use the same database state, parameters, cache policy, and capture method for before/after comparisons. Record whether the cache was warm or cold. Test at least two parameter shapes when skew or parameter sensitivity is plausible.
