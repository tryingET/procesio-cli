#!/usr/bin/env bash
# Start one checkpointed local Pi Gate 5 A/A run in the background.
#
# Usage:
#   bash scripts/start-local-pi-gate5-aa-unattended.sh \
#     scratchpad/gate5-aa-v2-YYYYMMDDTHHMMSSZ
#
# Optional environment overrides:
#   GATE5_MAX_HOURS=5
#   GATE5_BATCH_OBSERVATIONS=8
#   GATE5_MAX_MODEL_CALLS=120
#   GATE5_INITIAL_BACKOFF_SECONDS=300
#   GATE5_MAX_BACKOFF_SECONDS=1800
#   GATE5_BETWEEN_BATCHES_SECONDS=30
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd -P)"
RUN_ARG="${1:-}"

if [[ -z "$RUN_ARG" ]]; then
  cat >&2 <<'EOF'
Usage:
  bash scripts/start-local-pi-gate5-aa-unattended.sh \
    scratchpad/gate5-aa-v2-YYYYMMDDTHHMMSSZ
EOF
  exit 2
fi

if [[ "$RUN_ARG" = /* ]]; then
  RUN_DIR="$RUN_ARG"
else
  RUN_DIR="$ROOT/$RUN_ARG"
fi
if [[ ! -d "$RUN_DIR" ]]; then
  echo "ERROR: Gate 5 run directory does not exist: $RUN_DIR" >&2
  exit 2
fi
RUN_DIR="$(cd "$RUN_DIR" && pwd -P)"

METADATA="$RUN_DIR/run-metadata.json"
if [[ ! -f "$METADATA" ]]; then
  echo "ERROR: Missing run metadata: $METADATA" >&2
  echo "Adopt or start the checkpoint with run-local-pi-gate5-aa.py first." >&2
  exit 2
fi

LOG="$RUN_DIR/unattended.log"
PID_FILE="$RUN_DIR/unattended.pid"
STATUS="$RUN_DIR/unattended-status.json"

MAX_HOURS="${GATE5_MAX_HOURS:-5}"
BATCH_OBSERVATIONS="${GATE5_BATCH_OBSERVATIONS:-8}"
MAX_MODEL_CALLS="${GATE5_MAX_MODEL_CALLS:-120}"
INITIAL_BACKOFF="${GATE5_INITIAL_BACKOFF_SECONDS:-300}"
MAX_BACKOFF="${GATE5_MAX_BACKOFF_SECONDS:-1800}"
BETWEEN_BATCHES="${GATE5_BETWEEN_BATCHES_SECONDS:-30}"

if [[ -f "$PID_FILE" ]]; then
  EXISTING_PID="$(tr -d '[:space:]' < "$PID_FILE")"
  if [[ "$EXISTING_PID" =~ ^[0-9]+$ ]] && kill -0 "$EXISTING_PID" 2>/dev/null; then
    echo "Unattended Gate 5 A/A is already running as PID $EXISTING_PID"
    echo "Log: $LOG"
    echo "Status: $STATUS"
    exit 0
  fi
  rm -f "$PID_FILE"
fi

# Preserve the previous terminal status for diagnosis, but do not leave a stale
# error object looking like the state of the new launch.
if [[ -f "$STATUS" ]]; then
  cp "$STATUS" "$RUN_DIR/unattended-status.previous.json"
  rm -f "$STATUS"
fi

COMMAND=(
  uv run python "$ROOT/scripts/run-local-pi-gate5-aa-unattended.py"
  --resume-run "$RUN_DIR"
  --max-hours "$MAX_HOURS"
  --batch-observations "$BATCH_OBSERVATIONS"
  --initial-backoff-seconds "$INITIAL_BACKOFF"
  --max-backoff-seconds "$MAX_BACKOFF"
  --between-batches-seconds "$BETWEEN_BATCHES"
  --confirm-max-model-calls "$MAX_MODEL_CALLS"
)

cd "$ROOT"
printf '\n=== unattended Gate 5 A/A launch %s ===\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$LOG"

# Use systemd's sleep inhibitor only when the user session can actually talk to
# it. Otherwise plain nohup is more reliable than failing before Pi starts.
if command -v systemd-inhibit >/dev/null 2>&1 \
    && systemd-inhibit --list >/dev/null 2>&1; then
  nohup systemd-inhibit \
    --what=sleep:idle \
    --mode=block \
    --why="Gate 5 A/A skill evaluation" \
    env PYTHONUNBUFFERED=1 "${COMMAND[@]}" \
    >> "$LOG" 2>&1 </dev/null &
else
  nohup env PYTHONUNBUFFERED=1 "${COMMAND[@]}" \
    >> "$LOG" 2>&1 </dev/null &
fi

PID=$!
echo "$PID" > "$PID_FILE"

# Give Pi's detached preflight enough time to expose immediate model-selection,
# auth, executable, or metadata errors. A quota-limited coordinator remains
# alive because it backs off internally.
for ((ATTEMPT = 1; ATTEMPT <= 10; ATTEMPT++)); do
  sleep 1
  if ! kill -0 "$PID" 2>/dev/null; then
    rm -f "$PID_FILE"
    if [[ -f "$STATUS" ]] && grep -q '"status": "complete"' "$STATUS"; then
      echo "Gate 5 A/A completed during startup."
      cat "$STATUS"
      exit 0
    fi
    echo "ERROR: unattended Gate 5 A/A exited during startup." >&2
    if [[ -f "$STATUS" ]]; then
      cat "$STATUS" >&2
    else
      tail -n 40 "$LOG" >&2 || true
    fi
    exit 2
  fi
done

echo "Started unattended Gate 5 A/A as PID $PID"
echo "Run: $RUN_DIR"
echo "Log: $LOG"
echo "Status: $STATUS"
echo "Follow: tail -f '$LOG'"
