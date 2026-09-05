# PROCESIO examples

## Evidence Status Normalizer

`CLI Utility 01 - Evidence Status Normalizer` is a retained, manually invoked process in the `procesio-cli-pure-awesomeness` workspace. It converts an evaluation or field-run status object into a stable decision, summary, and next action.

Files:

- `evidence-status-normalizer.process.json` — portable compact process config;
- `evidence-status-normalizer.sample-payload.json` — representative Gate 5 status;
- `evidence-status-normalizer.field-trial.md` — bounded create/run/verify contract;
- `evidence-status-normalizer.deployment.json` — non-secret verified workspace deployment;
- `../../skills/evals/procesio-evidence-normalizer-field-v1.json` — sanitized field evidence.

Run the retained process with one status file:

```bash
uv run --script scripts/run-procesio-evidence-normalizer.py \
  --input scratchpad/gate5-series-v4-overnight/series-status.json
```

Or pipe JSON:

```bash
cat status.json | \
  uv run --script scripts/run-procesio-evidence-normalizer.py
```

Preview the scoped calls without accessing PROCESIO:

```bash
uv run --script scripts/run-procesio-evidence-normalizer.py \
  --input status.json --dry-run
```

Each non-dry invocation performs exactly one synchronous process execution, then reads that exact instance's output. It never retries a timeout or a missing-instance-ID response; those outcomes require instance reconciliation first.

The process intentionally has no webhook or form. The current REST webhook launch path is anonymous and asynchronous, so adding it would expose a public trigger without returning the normalized object directly. Use the scoped local caller unless a separately reviewed authenticated interface is introduced.
