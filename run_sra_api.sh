#!/usr/bin/env bash
set -euo pipefail

# Unified SRA runtime supervisor. Normal runtime logs are capped at 10 MB;
# the port-kill audit is permanent and is never truncated here.
BASE_DIR="${BASE_DIR:-/mntCZJ/TopicClassification/poc-agent}"
PORT="${PORT:-9002}"
MAX_SIZE_KB=$((10 * 1024))
MAX_SIZE=$((MAX_SIZE_KB * 1024))
API_LOG="${API_LOG:-SRA-API_output.txt}"
SCHEDULE_LOG="${SCHEDULE_LOG:-SRA-ScheduleWorker_output.txt}"
HANDOFF_LOG="${HANDOFF_LOG:-SRA-HandoffWorker_output.txt}"
KILL_AUDIT_LOG="${KILL_AUDIT_LOG:-SRA-API_kill_audit.log}"
LOCK_FILE="${LOCK_FILE:-$BASE_DIR/.run_sra_api.lock}"
SHUTDOWN_TIMEOUT_SECONDS="${SHUTDOWN_TIMEOUT_SECONDS:-10}"
PORT_RELEASE_TIMEOUT_SECONDS="${PORT_RELEASE_TIMEOUT_SECONDS:-10}"

cd "$BASE_DIR"

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "[run_sra_api] Another launcher is already running (lock: $LOCK_FILE)." >&2
  exit 1
fi
printf '%s\n' "$$" 1>&9

audit() {
  printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >> "$KILL_AUDIT_LOG"
}

process_start_time() {
  awk '{print $22}' "/proc/$1/stat" 2>/dev/null || true
}

process_is_live() {
  local pid="$1"
  kill -0 "$pid" 2>/dev/null || return 1
  [ "$(awk '{print $3}' "/proc/$pid/stat" 2>/dev/null || true)" != "Z" ]
}

is_expected_sra_api() {
  local pid="$1" cmd cwd
  [ -r "/proc/$pid/cmdline" ] || return 1
  cmd="$(tr '\0' ' ' < "/proc/$pid/cmdline")"
  cwd="$(readlink -f "/proc/$pid/cwd" 2>/dev/null || true)"
  [ "$cwd" = "$(readlink -f "$BASE_DIR")" ] || return 1
  [[ "$cmd" == *"uvicorn"* ]] || return 1
  [[ "$cmd" == *"api.main:app"* ]] || return 1
  [[ "$cmd" == *"--port $PORT"* || "$cmd" == *"--port=$PORT"* ]]
}

port_pids() {
  lsof -t -i "tcp:$PORT" 2>/dev/null | sort -u || true
}

inspect_port() {
  local pids pid cmd cwd start deadline remaining
  declare -A verified_start=()
  pids="$(port_pids)"
  [ -n "$pids" ] || { audit "Port $PORT is free"; return 0; }

  audit "Port $PORT collision detected"
  lsof -nP -i "tcp:$PORT" >> "$KILL_AUDIT_LOG" 2>&1 || true
  lsof -nP -i "tcp:$PORT" >&2 2>/dev/null || true

  for pid in $pids; do
    cmd="$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null || true)"
    cwd="$(readlink -f "/proc/$pid/cwd" 2>/dev/null || true)"
    start="$(process_start_time "$pid")"
    audit "PID=$pid start=$start cwd=$cwd cmd=$cmd"
    if ! is_expected_sra_api "$pid"; then
      audit "ABORT unverified port owner PID=$pid; no signal sent"
      echo "[run_sra_api] Port $PORT has an unrelated or unverified owner (PID $pid); refusing to kill it." >&2
      return 1
    fi
    verified_start["$pid"]="$start"
  done

  for pid in $pids; do
    start="$(process_start_time "$pid")"
    audit "Sending SIGTERM to verified stale SRA API PID=$pid start=$start"
    kill -TERM "$pid"
  done

  deadline=$((SECONDS + PORT_RELEASE_TIMEOUT_SECONDS))
  while [ "$SECONDS" -lt "$deadline" ] && [ -n "$(port_pids)" ]; do sleep 0.1; done
  remaining="$(port_pids)"
  for pid in $remaining; do
    start="$(process_start_time "$pid")"
    if is_expected_sra_api "$pid" && [ -n "$start" ] && [ "$start" = "${verified_start[$pid]:-}" ]; then
      audit "Sending SIGKILL to verified unresponsive SRA API PID=$pid start=$start"
      kill -KILL "$pid"
    else
      audit "ABORT port owner changed or became unverified PID=$pid; no SIGKILL sent"
      return 1
    fi
  done
  deadline=$((SECONDS + PORT_RELEASE_TIMEOUT_SECONDS))
  while [ "$SECONDS" -lt "$deadline" ] && [ -n "$(port_pids)" ]; do sleep 0.1; done
  if [ -n "$(port_pids)" ]; then
    audit "ABORT Port $PORT was not released"
    return 1
  fi
  audit "Port $PORT released after verified stale SRA API shutdown"
}

cap_log() {
  local file="$1" line size tmp
  while IFS= read -r line || [ -n "$line" ]; do
    printf '%s\n' "$line" >> "$file"
    size="$(stat -c%s "$file" 2>/dev/null || printf 0)"
    if [ "$size" -gt "$MAX_SIZE" ]; then
      tmp="${file}.cap.$$"
      tail -c "$MAX_SIZE" "$file" > "$tmp"
      mv -f "$tmp" "$file"
    fi
  done
}

declare -a CHILD_PIDS=()
declare -a CHILD_NAMES=()
CLEANED_UP=0
SIGNALLED=0

cleanup() {
  local pid deadline
  [ "$CLEANED_UP" -eq 0 ] || return 0
  CLEANED_UP=1
  trap - INT TERM
  for pid in "${CHILD_PIDS[@]:-}"; do
    process_is_live "$pid" && kill -TERM "$pid" 2>/dev/null || true
  done
  deadline=$((SECONDS + SHUTDOWN_TIMEOUT_SECONDS))
  while [ "$SECONDS" -lt "$deadline" ]; do
    local any=0
    for pid in "${CHILD_PIDS[@]:-}"; do process_is_live "$pid" && any=1; done
    [ "$any" -eq 1 ] || break
    sleep 0.1
  done
  for pid in "${CHILD_PIDS[@]:-}"; do
    process_is_live "$pid" && kill -KILL "$pid" 2>/dev/null || true
  done
  for pid in "${CHILD_PIDS[@]:-}"; do wait "$pid" 2>/dev/null || true; done
}

handle_signal() {
  SIGNALLED=1
  cleanup
  exit 0
}
trap handle_signal INT TERM
trap cleanup EXIT

inspect_port

# Normal logs may be reset for a new launch. The permanent audit log is append-only.
: > "$API_LOG"
: > "$SCHEDULE_LOG"
: > "$HANDOFF_LOG"

echo "[run_sra_api] Starting API + Requirement Schedule Worker + Requirement Handoff Worker"
echo "[run_sra_api] Base directory: $BASE_DIR; port: $PORT; runtime log cap: 10 MB"

uvicorn api.main:app --host 0.0.0.0 --port "$PORT" > >(cap_log "$API_LOG") 2>&1 &
CHILD_PIDS+=("$!"); CHILD_NAMES+=("SRA API")

WORKER_BOOTSTRAP='from config.bootstrap import bootstrap_env; bootstrap_env(); import sys; from requirement_scheduler.cli import main; raise SystemExit(main([sys.argv[1]]))'
python -c "$WORKER_BOOTSTRAP" schedule-worker > >(cap_log "$SCHEDULE_LOG") 2>&1 &
CHILD_PIDS+=("$!"); CHILD_NAMES+=("Requirement Schedule Worker")
python -c "$WORKER_BOOTSTRAP" handoff-worker > >(cap_log "$HANDOFF_LOG") 2>&1 &
CHILD_PIDS+=("$!"); CHILD_NAMES+=("Requirement Handoff Worker")

exited_pid=""
status=0
set +e
wait -n -p exited_pid "${CHILD_PIDS[@]}"
status=$?
set -e

exited_name="unknown child"
for i in "${!CHILD_PIDS[@]}"; do
  [ "${CHILD_PIDS[$i]}" = "$exited_pid" ] && exited_name="${CHILD_NAMES[$i]}"
done
echo "[run_sra_api] $exited_name exited unexpectedly with status $status; stopping the remaining runtime." >&2
cleanup
exit 1
