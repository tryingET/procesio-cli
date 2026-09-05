# Fixed-rubric Gate 5 overnight series

`scripts/run-local-pi-gate5-series-unattended.py` runs the complete synthetic Gate 5 comparison in a bounded, checkpointed sequence:

1. suite-v4 A/A against two byte-identical copies of the current skill corpus;
2. A/B round 1 against the frozen original two-skill corpus, only if A/A passes;
3. A/B round 2 against the same snapshots, only if round 1 passes; and
4. deterministic verification that both A/B reports passed with identical corpus fingerprints.

The default frozen baseline is commit `da12de643c8a2355d019f40515766abf80a819df`, containing `procesio-expert` and `sql-server-optimizer`. The candidate snapshot is the current five-skill corpus, including `agent-skill-engineer`. The run stores exact tracked-commit corpus, evaluator-runtime, suite, threshold, model, provider, and thinking-level fingerprints before the first model call.

The full minimum budget is:

```text
3 phases × 12 cases × 5 repetitions × 2 corpora = 360 observations
360 observations × 2 model calls = 720 model calls
+ at least one preflight call
```

The default hard cap of 900 allows bounded failed attempts and additional preflights. Completed observations are appended to each phase's `runs.jsonl`. Quota/rate-limit failures back off and resume the same phase. Any failed A/A or A/B gate stops the series; the coordinator never skips a gate or alters thresholds.

The evaluated agents receive read-only skill-file tools. The runner does not authenticate to or access PROCESIO.

## Completed suite-v4 evidence

The series completed on 2026-09-05 for:

- candidate commit: `a47135373c4c0598391e808939397cd139234afd`;
- candidate fingerprint: `036016a5908792fc9fac1f6d603586a61400e3649f7b42d990026f55b2d79f3b`;
- baseline commit: `da12de643c8a2355d019f40515766abf80a819df`;
- baseline fingerprint: `a85a68df6d19ed1c2a90d6ed08fd5cf1f2997e9b38878c6728a86ba93ef60ce1`;
- model: `opencode-go/muse-spark-1.3-contributor`;
- thinking level: `medium`;
- jury contract: `fixed-jury-rubric-v2`.

All three phases completed with 120 observations and passed. The deterministic series verifier accepted both consecutive A/B reports. The final A/B round measured:

| Metric | Candidate | Original baseline | Delta |
|---|---:|---:|---:|
| selection accuracy | 98.33% | 33.33% | +65.00 pp |
| task success | 86.67% | 33.33% | +53.33 pp |
| forbidden collision rate | 0% | 0% | 0 pp |

The committed evidence record is `local-pi-gate5-suite-v4-passed.json`. Raw phase reports and sanitized JSONL observations remain in the operator's gitignored `scratchpad/gate5-series-v4-overnight/` directory.

This pass is scoped to the frozen candidate commit and fingerprint above. The `agent-skill-engineer` package was materially changed after that snapshot, so the newer loaded skill corpus must be restored to the evaluated version or separately revalidated before current `main` can be marked release-eligible.

## Recommended eight-hour invocation

```bash
PI_EVAL_MODEL='opencode-go/muse-spark-1.3-contributor' \
PI_EVAL_THINKING='medium' \
bash scripts/start-local-pi-gate5-series-overnight.sh
```

Defaults:

- run root: `scratchpad/gate5-series-v4-overnight`
- wall-clock limit: eight hours
- batch size: eight observations
- model-call cap: 900 for the invocation
- initial quota backoff: five minutes
- maximum quota backoff: 30 minutes

The command runs in the foreground so progress remains visible. On systems where the current user can use `systemd-inhibit`, the launcher blocks ordinary sleep/idle suspension for the duration.

The launcher is idempotent for its run root: invoking it again resumes compatible checkpoints instead of recreating completed observations. It refuses changed model, provider, thinking level, repetition count, corpus, suite, thresholds, or frozen evaluator runtime.

## Status inspection

```bash
cat scratchpad/gate5-series-v4-overnight/series-status.json
```

Interpretation:

- `status: complete`, `stop_reason: gate5_series_passed`, `gate5_evidence: true`: A/A and both A/B rounds passed.
- `status: blocked`: a completed gate failed; do not rerun automatically or loosen thresholds.
- `status: paused`: the wall-clock or call cap was reached; rerun the same launcher to resume.
- `status: backing_off`: the provider is temporarily quota/rate limited and the coordinator is waiting.
- `status: error`: a non-retryable setup or evaluator problem occurred.

All phase reports and raw sanitized observations remain under `scratchpad/gate5-series-v4-overnight/phases/`.
