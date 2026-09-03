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

A `quota_exhausted` or `model_not_available` result means no skill evaluation began. Do not change the skill corpus in response to a provider/model failure.

## 3. Pin the same model for the skill runner

```bash
export PI_EVAL_MODEL='<provider/model-id>'
```

Then run the single-case smoke request through `scripts/pi-skill-eval-runner.py`.

Optional reproducibility controls:

```bash
export PI_EVAL_PROVIDER='<provider>'
export PI_EVAL_THINKING='low'
```

Do not export or paste Pi's OAuth/API credentials. The Pi CLI resolves its own local authentication.

## Call budget

The current behavioral corpus has eight cases. One paired round with five repetitions and two corpora invokes the runner 80 times. The current Pi runner uses one fresh agent call and one fresh judge call per invocation, so one full round uses 160 model calls. The required A/A plus two A/B rounds would use 480 model calls.

Therefore:

- run the one-call preflight first;
- run one two-call smoke case second;
- do not launch the full Gate 5 sequence on a limited subscription accidentally;
- use a deliberately selected model/provider with adequate quota, or a controlled local inference endpoint;
- retain the same pinned model and thinking level across A/A and A/B evidence.

The high call count is an explicit optimization target; it is not evidence that the skill corpus failed.
