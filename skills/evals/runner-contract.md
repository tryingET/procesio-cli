# Behavioral evaluation runner contract

`run-skill-behavior-evals.py` launches an external model harness as an argv list, never through a shell. The command receives one JSON object on stdin and must print exactly one JSON object on stdout.

## Required experiment order

1. Run `--mode aa` with byte-identical corpora in two independent directories. The selection, task-success, and collision deltas must stay inside the pre-registered noise limits.
2. Run `--mode ab` against the frozen old corpus and candidate corpus with the same command, cases, repetitions, and controlled seeds.
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
