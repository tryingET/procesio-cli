# Deterministic optimizer controller contract

Use this reference when initializing, staging, accepting, rejecting, inspecting, or finalizing a skill-optimization experiment with `scripts/optimize_skill.py`.

## Contents

1. Purpose and non-goals
2. Objective file
3. Validation report
4. Final test report
5. Lifecycle
6. Exit and state semantics
7. Security and reproducibility

## 1. Purpose and non-goals

The controller protects experiment integrity. It does not generate edits, call a model, judge responses, or prove that a rubric is valid.

It provides:

- immutable baseline and best-skill snapshots;
- path-confined package copies and fingerprints;
- allowlisted edit surfaces;
- line, file, and binary edit budgets;
- validation-report identity checks;
- hard-constraint and non-regression gates;
- strict better-than-current-best promotion;
- rejected-candidate history and plateau stopping;
- untouched final-test separation;
- atomic machine-readable state.

## 2. Objective file

The objective is immutable after `init`. Use this structure:

```json
{
  "schema_version": 1,
  "experiment_id": "incident-triage-v1",
  "primary_metric": "task_success_rate",
  "min_primary_delta": 0.05,
  "higher_is_better": true,
  "max_regression_rate": 0.02,
  "minimum_valid_pairs": 40,
  "hard_constraints": [
    "no_forbidden_routing_collision",
    "no_unapproved_mutation"
  ],
  "secondary_metrics": {
    "mean_total_tokens": {
      "direction": "lower",
      "max_relative_regression": 0.15
    },
    "mean_duration_ms": {
      "direction": "lower",
      "max_relative_regression": 0.20
    }
  },
  "edit_budget": {
    "max_changed_files": 4,
    "max_added_lines": 80,
    "max_deleted_lines": 80,
    "max_total_changed_lines": 120,
    "max_binary_bytes": 0
  },
  "allowed_paths": [
    "SKILL.md",
    "references/*.md",
    "scripts/*.py"
  ],
  "forbidden_paths": [
    "evals/**",
    ".git/**"
  ],
  "plateau_limit": 3,
  "validation_identity": {
    "corpus_fingerprint": "sha256:...",
    "rubric_fingerprint": "sha256:...",
    "model_fingerprint": "provider:model:settings",
    "harness_fingerprint": "sha256:...",
    "pairing_fingerprint": "sha256:..."
  },
  "test_identity": {
    "corpus_fingerprint": "sha256:different-from-validation",
    "rubric_fingerprint": "sha256:...",
    "model_fingerprint": "provider:model:settings",
    "harness_fingerprint": "sha256:...",
    "pairing_fingerprint": "sha256:..."
  }
}
```

Rules:

- `primary_metric` must appear in every baseline and candidate report.
- A candidate must improve the current best by at least `min_primary_delta` in the configured direction.
- `minimum_valid_pairs` applies to paired validation and final test.
- Every named hard constraint must appear as JSON Boolean `true` in the candidate report.
- `max_regression_rate` is computed from paired baseline-success → candidate-failure transitions.
- Secondary limits apply only after eligibility and primary improvement pass.
- `evals/**` and `.git/**` are always protected even if omitted.
- All numeric values must be finite; NaN and infinity are rejected.

## 3. Validation report

Initialize with an immutable baseline validation report. Candidate reports use the same identity and metric schema:

```json
{
  "schema_version": 1,
  "split": "validation",
  "candidate_fingerprint": "sha256:...",
  "parent_fingerprint": "sha256:...",
  "identity": {
    "corpus_fingerprint": "sha256:...",
    "rubric_fingerprint": "sha256:...",
    "model_fingerprint": "provider:model:settings",
    "harness_fingerprint": "sha256:...",
    "pairing_fingerprint": "sha256:..."
  },
  "valid_pairs": 40,
  "paired_outcomes": {
    "repairs": 8,
    "regressions": 1,
    "preserved_successes": 25,
    "unresolved_failures": 6
  },
  "metrics": {
    "task_success_rate": 0.825,
    "mean_total_tokens": 2900,
    "mean_duration_ms": 5100
  },
  "hard_constraints": {
    "no_forbidden_routing_collision": true,
    "no_unapproved_mutation": true
  }
}
```

The four paired outcome counts must sum exactly to `valid_pairs`. The controller rejects stale parent/candidate fingerprints, wrong split, missing identity fields, non-finite metrics, missing hard constraints, insufficient pairs, excessive regressions, non-improvement, and secondary-cost violations.

The baseline report supplied to `init` uses the baseline package fingerprint as both candidate and parent fingerprint. Its metrics define the initial best score and secondary-cost reference.

## 4. Final test report

After validation selects a candidate, run one untouched paired test against the **original baseline**, not against a validation-tuned intermediate:

```json
{
  "schema_version": 1,
  "split": "test",
  "candidate_fingerprint": "sha256:selected-best",
  "parent_fingerprint": "sha256:original-baseline",
  "identity": {
    "corpus_fingerprint": "sha256:untouched-test",
    "rubric_fingerprint": "sha256:...",
    "model_fingerprint": "provider:model:settings",
    "harness_fingerprint": "sha256:...",
    "pairing_fingerprint": "sha256:..."
  },
  "valid_pairs": 80,
  "paired_outcomes": {
    "repairs": 14,
    "regressions": 2,
    "preserved_successes": 51,
    "unresolved_failures": 13
  },
  "metrics": {
    "task_success_rate": 0.8125,
    "mean_total_tokens": 2850,
    "mean_duration_ms": 5000
  },
  "hard_constraints": {
    "no_forbidden_routing_collision": true,
    "no_unapproved_mutation": true
  }
}
```

The test corpus fingerprint must differ from validation. `finalize` refuses an ineligible final report and never writes the output package on failure.

## 5. Lifecycle

### Initialize

```bash
python skills/agent-skill-engineer/scripts/optimize_skill.py init \
  --skill-root skills/example \
  --workspace .skill-optimization/example \
  --objective objective.json \
  --baseline-report baseline-validation.json
```

Creates immutable `baseline/`, `best/`, objective, state, and ledger artifacts. The workspace must not already exist.

### Stage

```bash
python skills/agent-skill-engineer/scripts/optimize_skill.py stage \
  --workspace .skill-optimization/example \
  --candidate-root work/candidate \
  --hypothesis "Replace blind retry with unknown-outcome reconciliation"
```

Copies the candidate, verifies its parent, checks the path allowlist and edit budget, and assigns `c0001`, `c0002`, and so on. A staged candidate is immutable.

### Decide

```bash
python skills/agent-skill-engineer/scripts/optimize_skill.py decide \
  --workspace .skill-optimization/example \
  --candidate-id c0001 \
  --report c0001-validation.json
```

Accepts only a strictly eligible improvement over the current best. Otherwise records the candidate and reasons in the rejected ledger. An accepted candidate becomes a new immutable best snapshot.

### Status

```bash
python skills/agent-skill-engineer/scripts/optimize_skill.py status \
  --workspace .skill-optimization/example
```

Returns fingerprints, current score, accepted/rejected history, plateau count, and experiment state.

### Finalize

```bash
python skills/agent-skill-engineer/scripts/optimize_skill.py finalize \
  --workspace .skill-optimization/example \
  --report final-test.json \
  --out dist/example-skill
```

Validates untouched test evidence and writes the selected package to a new output path. It never overwrites an existing path.

## 6. Exit and state semantics

- Exit `0`: operation completed and returned a valid state/result.
- Exit `2`: bounded contract failure, invalid candidate, rejected promotion, failed final test, or state conflict.
- Exit `1`: unexpected internal failure.

State values:

- `active`: candidates may be staged and decided.
- `plateaued`: the registered consecutive-rejection limit was reached; new staging is refused until a new experiment is initialized.
- `finalized`: final test passed and output package was emitted; mutation of the experiment is refused.

A rejected candidate is a normal experimental outcome, not an internal error. Preserve its evidence.

## 7. Security and reproducibility

- The controller performs no network or model calls.
- It refuses symlinks, absolute or traversal paths, environment/cache directories, and non-finite JSON.
- It copies package files into immutable snapshots rather than trusting mutable source paths.
- It checks state, objective, and snapshot fingerprints before every mutation.
- It protects formal evaluation data from candidate edits.
- It writes state and reports atomically.
- It records hypotheses, diffs, fingerprints, metrics, and rejection reasons.
- It cannot prove that an evaluator is unbiased or that a task distribution is representative; those remain evaluation-design responsibilities.
