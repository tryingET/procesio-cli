# Behavioral evaluation runner contract

`run-skill-behavior-evals.py` launches an external model harness as an argv list, never through a shell. The command receives one JSON object on stdin and must print exactly one JSON object on stdout.

## Required experiment order

1. Run `--mode aa` with byte-identical corpora in two independent directories. Selection, host-computed task success, and collision deltas must remain inside the pre-registered noise limits.
2. Run `--mode ab` against the frozen old corpus and candidate corpus with the same command, cases, repetitions, controlled seeds, provider, model, thinking level, and rubric contract.
3. Produce at least the number of consecutive passing A/B reports required by `gate5-thresholds.json`.
4. Do not revise thresholds after seeing results. A failed A/A run invalidates the subsequent comparison until the response and judging variance is understood.

Changing a prompt, criterion, judge contract, aggregation rule, or case definition creates a new suite version and requires a new A/A run from observation zero.

## Request

- `run_id`: unique paired-run ID.
- `variant_label`: opaque A/B label.
- `skills_root`: local directory containing the corpus for this run.
- `task`: user prompt.
- `expected_output`: the fixed jury rubric object shown below.
- `output_contract`: required result fields.

The runner must not map the opaque label to candidate or baseline.

### Fixed jury rubric

Every formal case supplies one ordered rubric object:

```json
{
  "rubric_version": 1,
  "criteria": [
    {
      "id": "classifies_timeout_as_unknown_outcome",
      "description": "Pass only when the response explicitly states that a timeout is an unknown outcome.",
      "required": true
    },
    {
      "id": "reconciles_existing_instances_before_retry",
      "description": "Pass only when existing instances are reconciled before retry.",
      "required": true
    }
  ]
}
```

The criterion IDs, order, wording, and required flags are evaluation data. A juror must not invent, rename, merge, split, omit, or add criteria. Every juror evaluating the same case receives the same rubric bytes from the frozen suite file.

`task_success` is not a juror opinion. The host computes it as:

```text
rubric contract valid
AND every required criterion ID is present exactly once
AND every required criterion value is the JSON boolean true
```

Objective routing is measured separately by comparing `selected_skill` with `expected_skill`. It is not duplicated as a subjective jury criterion.

## Result

Print one object:

```json
{
  "selected_skill": "procesio-cli",
  "task_success": true,
  "response": "...",
  "assertion_results": {
    "classifies_timeout_as_unknown_outcome": true,
    "reconciles_existing_instances_before_retry": true
  },
  "grader_contract": "fixed-jury-rubric-v2",
  "criterion_ids": [
    "classifies_timeout_as_unknown_outcome",
    "reconciles_existing_instances_before_retry"
  ],
  "criteria_fingerprint": "sha256...",
  "total_tokens": 1234
}
```

Diagnostic logs belong on stderr. Do not include model or API secrets, credentials, or sensitive test payloads. The wrapper stores stdout results as evaluation artifacts, so use only sanitized fixtures and controlled environments.

## Local Pi adapter

`scripts/pi-skill-eval-runner.py` provides corpus isolation and two fresh Pi contexts: one response context and one no-tools judge context. It never accepts or prints a provider API key.

`scripts/pi-skill-eval-runner-strict.py` is the Gate-quality wrapper. It:

1. Validates the supplied rubric before making model calls.
2. Serializes the same canonical rubric into every judge prompt.
3. Requires the judge to return exactly the supplied criterion IDs with Boolean values.
4. Normalizes missing criteria to `false` and rejects unexpected criteria.
5. Computes `task_success` in Python from the required Boolean results instead of trusting a model-generated aggregate.
6. Records a SHA-256 rubric fingerprint with the observation.

The old suite-v2 prompt gave all judges the same prose expectation but asked each judge to derive its own two-to-five assertions. That dynamic decomposition was an evaluator defect. Suite v3 removes it.

### Read-only evaluation semantics

The Pi behavior runner deliberately cannot access network services, edit the repository, or mutate a PROCESIO workspace. It evaluates routing, decisions, safety sequencing, implementation plans, verification plans, and truthful reporting.

Therefore:

- A behavioral case that would normally require a code or workspace mutation must explicitly ask for a plan, review, diagnosis, or approval checkpoint.
- A criterion must not require completed external actions from a read-only candidate.
- An honest statement that execution or proof remains unavailable is correct when the criterion asks for a plan.
- Fabricated claims that files, tests, API calls, or platform changes were completed are failures.
- Actual mutation and runtime behavior belong in controlled field trials and integration tests, not this blinded read-only comparison.

### Pin the model

`PI_EVAL_MODEL` is required. A gate result is not reproducible when it silently follows whichever Pi default model happens to be active.

```bash
pi --list-models
export PI_EVAL_MODEL='<provider>/<model-id>'
export PI_EVAL_THINKING=medium
```

When a provider must be supplied separately:

```bash
export PI_EVAL_PROVIDER='<provider>'
export PI_EVAL_MODEL='<model-id>'
```

The adapter passes the selected model through both `--model` and `--models`, so stale user-level model patterns cannot silently alter the experiment.

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
  "expected_output": {
    "rubric_version": 1,
    "criteria": [
      {
        "id": "classifies_timeout_as_unknown_outcome",
        "description": "Pass only when the response states that timeout is an unknown outcome.",
        "required": true
      },
      {
        "id": "prevents_duplicate_execution",
        "description": "Pass only when the response refuses a blind retry because it could duplicate execution.",
        "required": true
      }
    ]
  }
}
JSON
```

A model configuration or quota failure prints a structured `runner_error` object. A full Gate 5 sequence is intentionally much larger: each behavioral observation uses one response call and one independent judge call, and the registered gate requires a fresh A/A noise run plus two repeated A/B rounds.
