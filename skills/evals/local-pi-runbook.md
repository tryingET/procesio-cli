# Local Pi behavioral-evaluation runbook

Use Pi's existing local authentication, but pin an exact model for every evaluation. Do not rely on Pi's global default or scoped-model patterns: they can be stale, unavailable, or point to an account whose quota is exhausted.

## 1. Choose an exact model

List the model identifiers known to Pi:

```bash
pi --list-models
```

The interactive alternative is `/model`; Pi supports saving the selected startup model with `Ctrl+S`. For reproducible evaluations, still copy the full provider/model identifier and pass it explicitly.

## 2. Run the one-call preflight

```bash
uv run python scripts/pi-eval-preflight.py --model '<provider/model-id>'
```

Success is:

```json
{"ready": true, "marker_seen": true, "model": "<provider/model-id>"}
```

The preflight passes both the selected `--model` and the same exact identifier through `--models`. This overrides stale user-level `enabledModels` patterns, including in detached/no-TTY runs, and matches the behavioral runner's model-selection behavior.

A `quota_exhausted` or `model_not_available` result means no skill evaluation began. Do not change the skill corpus in response to a provider/model failure.

## 3. Pin the same model for every observation

```bash
export PI_EVAL_MODEL='<provider/model-id>'
export PI_EVAL_THINKING='medium'
```

Do not change the model, provider, thinking level, corpus snapshot, suite version, repetition count, or seed while resuming one formal experiment. Do not export or paste Pi's OAuth/API credentials; Pi resolves its own local authentication.

## 4. Use checkpointed batches

The formal A/A suite currently has eight cases and five repetitions over two byte-identical corpora:

```text
8 cases × 5 repetitions × 2 corpora = 80 observations
80 observations × 2 calls = 160 model calls
```

Every completed observation is appended to `results/runs.jsonl`. A quota or rate-limit response writes `results/partial-report.json` and exits with code `75`; this means **incomplete but resumable**, not a skill failure.

Start a deliberately small batch:

```bash
PI_EVAL_MODEL='<provider/model-id>' \
PI_EVAL_THINKING='medium' \
uv run python scripts/run-local-pi-gate5-aa.py \
  --max-new-observations 8 \
  --confirm-model-calls 16
```

Resume the exact run directory printed by the command:

```bash
PI_EVAL_MODEL='<same-provider/model-id>' \
PI_EVAL_THINKING='medium' \
uv run python scripts/run-local-pi-gate5-aa.py \
  --resume-run scratchpad/gate5-aa-v2-YYYYMMDDTHHMMSSZ \
  --max-new-observations 8 \
  --confirm-model-calls 16
```

Runs created before automatic resume metadata require a one-time confirmation of the existing checkpoint count:

```bash
uv run python scripts/run-local-pi-gate5-aa.py \
  --resume-run scratchpad/gate5-aa-v2-YYYYMMDDTHHMMSSZ \
  --confirm-existing-observations 12 \
  --max-new-observations 8 \
  --confirm-model-calls 16
```

After that first adoption, omit `--confirm-existing-observations`; the saved metadata locks the model, thinking level, suite, seed, corpus fingerprint, thresholds, and strict runner. The harness skips completed `(case, repetition, corpus)` jobs and never truncates the checkpoint.

For manual operation, do not immediately retry a quota response: run the one-call preflight first, then resume the same directory. A different model requires a new experiment from observation zero.

## 5. Run one checkpoint unattended

`scripts/run-local-pi-gate5-aa-unattended.py` automates only the current A/A phase. It reads the locked model and thinking level from `run-metadata.json`, runs a preflight, resumes in bounded batches, and uses exponential backoff after quota/rate-limit responses. It stops at the wall-clock deadline, hard model-call cap, A/A completion, or a non-retryable error.

It never starts A/B and never accesses PROCESIO. It writes its latest state to `unattended-status.json` inside the run directory.

Use the checked-in detached launcher instead of composing a nested `nohup bash -lc` command:

```bash
bash scripts/start-local-pi-gate5-aa-unattended.sh \
  scratchpad/gate5-aa-v2-YYYYMMDDTHHMMSSZ
```

The launcher:

- uses the current shell's Pi, PATH, HOME, and local authentication;
- does not start a login shell;
- rejects a second live process for the same checkpoint;
- removes stale PID state and archives the previous terminal status;
- appends logs to `unattended.log`;
- uses `systemd-inhibit` only when the current user session supports it;
- defaults to five hours, batches of eight observations, and a 120-call hard cap.

Optional bounded overrides:

```bash
GATE5_MAX_HOURS=3 \
GATE5_BATCH_OBSERVATIONS=4 \
GATE5_MAX_MODEL_CALLS=60 \
bash scripts/start-local-pi-gate5-aa-unattended.sh \
  scratchpad/gate5-aa-v2-YYYYMMDDTHHMMSSZ
```

The call cap includes preflight attempts and an upper bound for evaluation calls. A completed A/A run stops immediately even when time or call budget remains. An A/A noise-gate failure also stops immediately for inspection; the coordinator does not roll into A/B.

## 6. Formal order

1. Complete the byte-identical A/A noise-floor run.
2. Inspect its report before starting A/B.
3. Run two blinded A/B rounds with the frozen baseline and exactly the same model and thinking level.
4. Do not revise thresholds after viewing formal results.

The checkpoint mechanism prevents provider limits from converting a long formal run into an all-or-nothing operation; it does not weaken the registered Gate 5 thresholds.
