#!/usr/bin/env bash
# Run or resume the complete fixed-rubric Gate 5 series in the foreground.
#
# Required:
#   PI_EVAL_MODEL='<provider/model-id>'
#
# Optional:
#   PI_EVAL_THINKING=medium
#   GATE5_RUN_ROOT=scratchpad/gate5-series-v3-overnight
#   GATE5_MAX_HOURS=8
#   GATE5_MAX_MODEL_CALLS=560
#   GATE5_BATCH_OBSERVATIONS=8
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd -P)"
MODEL="${PI_EVAL_MODEL:-}"
THINKING="${PI_EVAL_THINKING:-medium}"
RUN_ROOT="${GATE5_RUN_ROOT:-$ROOT/scratchpad/gate5-series-v3-overnight}"
MAX_HOURS="${GATE5_MAX_HOURS:-8}"
MAX_CALLS="${GATE5_MAX_MODEL_CALLS:-560}"
BATCH="${GATE5_BATCH_OBSERVATIONS:-8}"

if [[ -z "$MODEL" ]]; then
  echo "ERROR: PI_EVAL_MODEL must contain an exact provider/model ID." >&2
  exit 2
fi

COMMAND=(
  uv run python "$ROOT/scripts/run-local-pi-gate5-series-unattended.py"
  --run-root "$RUN_ROOT"
  --max-hours "$MAX_HOURS"
  --batch-observations "$BATCH"
  --initial-backoff-seconds 300
  --max-backoff-seconds 1800
  --between-batches-seconds 30
  --confirm-max-model-calls "$MAX_CALLS"
)

cd "$ROOT"
echo "Starting/resuming the fixed-jury Gate 5 series."
echo "Model: $MODEL; thinking: $THINKING"
echo "Run root: $RUN_ROOT"
echo "Bounds: $MAX_HOURS hours; at most $MAX_CALLS model calls this invocation."
echo "Status: $RUN_ROOT/series-status.json"

if command -v systemd-inhibit >/dev/null 2>&1 \
    && systemd-inhibit --list >/dev/null 2>&1; then
  exec systemd-inhibit \
    --what=sleep:idle \
    --mode=block \
    --why="Fixed-rubric Gate 5 skill evaluation" \
    env PI_EVAL_MODEL="$MODEL" PI_EVAL_THINKING="$THINKING" \
    "${COMMAND[@]}"
fi

exec env PI_EVAL_MODEL="$MODEL" PI_EVAL_THINKING="$THINKING" \
  "${COMMAND[@]}"
