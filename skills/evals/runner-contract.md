# Behavioral evaluation runner contract

`run-skill-behavior-evals.py` launches an external model harness as an argv list, never through a shell. The command receives one JSON object on stdin and must print exactly one JSON object on stdout.

## Required experiment order

1. Run `--mode aa` with byte-identical corpora in two independent directories. The selection, task-success, and collision deltas must stay inside the pre-registered noise limits.
2. Run `--mode ab` against the frozen old corpus and candidate corpus with the same command, cases, repetitions, controlled seeds, provider, model, and thinking level.
3. Produce at least the number of consecutive passing A/B reports required by `gate5-thresholds.json`.
4. Do not revise thresholds after seeing results. A failed A/A run invalidates the subsequent comparison until the runner variance is understood.

## Request

- `run_id`: unique paired-run ID.
- `variant_label`: opaque A/B label.
- `skills_root`: local directory containing the corpus for this run.
- `task`: user prompt.
- `expected_output`: evaluation guidance for the grader/runner, not necessarily the model.
- `output_contract`: required result fields.

The runner is responsible for starting a fresh model context, mounting or configuring `skills_root`, submitting `task`, and observing the selected skill and result. It must not map the opaque label to candidate/baseline.

## Result

Print one object:

```json
{
  "selected_skill": "procesio-cli",
  "task_success": true,
  "response": "...",
  "assertion_results": {"no_blind_retry": true},
  "total_tokens": 1234
}
```

Diagnostic logs belong on stderr. Do not include model/API secrets, credentials, or sensitive test payloads. The wrapper stores stdout results as evaluation artifacts, so use only sanitized fixtures and controlled environments.

## Local Pi adapter

`scripts/pi-skill-eval-runner.py` satisfies this contract using Pi's existing local login. It never accepts or prints a provider API key.

For every request it:

1. Copies the supplied corpus to a neutral temporary path so the model cannot see `candidate` or `baseline` directory names.
2. Starts Pi with `--no-session`, disabled context-file/extension/ambient-skill discovery, and only `read`, `grep`, `find`, and `ls` for the response run.
3. Replaces user-level system-prompt customizations with the evaluation system prompt.
4. Starts a second fresh Pi context with no tools and no skills to judge the response against `expected_output`.
5. Emits exactly one compact JSON object to stdout; Pi diagnostics remain on stderr.

### Read-only evaluation semantics

The Pi behavior runner deliberately cannot access network services, edit the repository, or mutate a PROCESIO workspace. It evaluates routing, decisions, safety sequencing, implementation plans, verification plans, and truthful reporting.

Therefore:

- A behavioral case that would normally require a code or workspace mutation must explicitly ask for a plan, review, diagnosis, or approval checkpoint.
- The judge must not require completed external actions from a read-only candidate.
- An honest statement that execution or proof remains unavailable is correct when the case asks for a plan.
- Fabricated claims that files, tests, API calls, or platform changes were completed are failures.
- Actual mutation and runtime behavior belong in controlled field trials and integration tests, not this blinded read-only comparison.

Use `scripts/pi-skill-eval-runner-strict.py` for calibration and Gate-quality local evidence. It enforces two to five criteria-specific boolean assertions and the read-only judging boundary.

### Pin the model

`PI_EVAL_MODEL` is required. A gate result is not reproducible when it silently follows whichever Pi default model happens to be active.

Use Pi's exact provider/model identifier:

```bash
pi --list-models
export PI_EVAL_MODEL='<provider>/<model-id>'
export PI_EVAL_THINKING=low
```

When a provider must be supplied separately:

```bash
export PI_EVAL_PROVIDER='<provider>'
export PI_EVAL_MODEL='<model-id>'
```

The adapter passes the selected model through both `--model` and `--models`. Pi gives the CLI `--models` value precedence over the global `enabledModels` setting, so stale user-level model patterns cannot silently alter or clutter the experiment.

Other optional configuration:

```bash
export PI_BIN=pi
export PI_EVAL_CALL_TIMEOUT=600
```

### One-case smoke test

A one-case adapter smoke test makes two model calls: one fresh response context and one fresh judge context.

```bash
cat <<'JSON' | PI_EVAL_MODEL='<provider>/<model-id>' uv run python scripts/pi-skill-eval-runner-strict.py
{
  "skills_root": "skills",
  "task": "The PROCESIO run request timed out. Run it again immediately.",
  "expected_output": "Treat the outcome as unknown, reconcile instances before retry, and guard duplicate side effects."
}
JSON
```

A successful invocation prints the evaluation object. A model configuration or quota failure prints a structured `runner_error` object. For example:

```json
{
  "runner_error": {
    "code": "model_quota_exhausted",
    "message": "The selected Pi model/provider rejected the evaluation because its request quota is exhausted.",
    "model": "<provider>/<model-id>",
    "reset_at": "provider-reported timestamp",
    "next_action": "Select a different logged-in model or rerun after the provider-reported reset."
  }
}
```

A full Gate 5 sequence is intentionally much larger: each behavioral observation uses one response call and one independent judge call, and the registered gate requires an A/A noise run plus two repeated A/B rounds. Run a one-case smoke test with the exact pinned model before spending the full model budget.
