# Behavioral evaluation runner contract

`run-skill-behavior-evals.py` launches an external model harness as an argv list, never through a shell. The command receives one JSON object on stdin and must print exactly one JSON object on stdout.

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

Diagnostic logs belong on stderr. Do not include model/API secrets. Run A/A first by passing the same corpus through two independent directories; register thresholds before old-vs-candidate runs.
