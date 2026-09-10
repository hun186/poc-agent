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
LAUNCHER_IDENTITY_FILE="${LAUNCHER_IDENTITY_FILE:-$BASE_DIR/.run_sra_api_launcher.identity}"
TAKEOVER_LOCK_FILE="${TAKEOVER_LOCK_FILE:-$BASE_DIR/.run_sra_api_takeover.lock}"
SHUTDOWN_TIMEOUT_SECONDS="${SHUTDOWN_TIMEOUT_SECONDS:-10}"
PORT_RELEASE_TIMEOUT_SECONDS="${PORT_RELEASE_TIMEOUT_SECONDS:-10}"
API_IDENTITY_FILE="${API_IDENTITY_FILE:-$BASE_DIR/.run_sra_api_api.identity}"
SCHEDULE_IDENTITY_FILE="${SCHEDULE_IDENTITY_FILE:-$BASE_DIR/.run_sra_api_schedule.identity}"
HANDOFF_IDENTITY_FILE="${HANDOFF_IDENTITY_FILE:-$BASE_DIR/.run_sra_api_handoff.identity}"
HANDOFF_STATE_FILE=""
API_READINESS_TIMEOUT_SECONDS="${API_READINESS_TIMEOUT_SECONDS:-15}"
LAUNCHER_UID="$(id -u)"
RUNTIME_HOSTNAME="$(hostname)"
INVOCATION_START_TIME="$(awk '{print $22}' "/proc/$$/stat")"

cd "$BASE_DIR"

# Opening read/write is deliberately non-truncating: a restart contender must not
# destroy the current owner's evidence before it has proved lock ownership.
exec 9<>"$LOCK_FILE"
exec 8<>"$TAKEOVER_LOCK_FILE"

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

process_effective_uid() {
  awk '/^Uid:/{print $3; exit}' "/proc/$1/status" 2>/dev/null || true
}

launcher_cmdline_matches() {
  local pid="$1" resolved=""; local -a args=()
  mapfile -d '' -t args < "/proc/$pid/cmdline" 2>/dev/null || return 1
  [ "${#args[@]}" -ge 2 ] && [ "${args[0]##*/}" = bash ] || return 1
  if [[ "${args[1]}" = /* ]]; then resolved="$(readlink -f "${args[1]}" 2>/dev/null || true)"
  else resolved="$(readlink -f "/proc/$pid/cwd/${args[1]}" 2>/dev/null || true)"; fi
  [ "$resolved" = "$(readlink -f "$0")" ]
}

read_launcher_identity() {
  local key value count=0 record_pid="" record_start="" record_uid="" record_cwd="" record_path=""
  [ -f "$LAUNCHER_IDENTITY_FILE" ] && [ ! -L "$LAUNCHER_IDENTITY_FILE" ] || return 1
  [ "$(stat -c%u "$LAUNCHER_IDENTITY_FILE" 2>/dev/null || true)" = "$LAUNCHER_UID" ] || return 1
  [ "$(stat -c%a "$LAUNCHER_IDENTITY_FILE" 2>/dev/null || true)" = 600 ] || return 1
  while IFS='=' read -r key value; do
    count=$((count + 1)); case "$key" in
      pid) record_pid="$value";; process_start_time) record_start="$value";;
      effective_uid) record_uid="$value";; cwd) record_cwd="$value";; launcher_path) record_path="$value";;
      *) return 1;;
    esac
  done < "$LAUNCHER_IDENTITY_FILE"
  [ "$count" -eq 5 ] && [[ "$record_pid" =~ ^[0-9]+$ ]] && [[ "$record_start" =~ ^[0-9]+$ ]] || return 1
  [ "$record_uid" = "$LAUNCHER_UID" ] && [ "$record_cwd" = "$(readlink -f "$BASE_DIR")" ] || return 1
  [ "$record_path" = "$(readlink -f "$0")" ] || return 1
  LAUNCHER_RECORD_PID="$record_pid"; LAUNCHER_RECORD_START="$record_start"
}

launcher_process_matches() {
  local pid="$1" start="$2"
  process_is_live "$pid" && [ "$(process_start_time "$pid")" = "$start" ] &&
    [ "$(process_effective_uid "$pid")" = "$LAUNCHER_UID" ] &&
    [ "$(readlink -f "/proc/$pid/cwd" 2>/dev/null || true)" = "$(readlink -f "$BASE_DIR")" ] &&
    launcher_cmdline_matches "$pid"
}

write_launcher_identity() {
  local start tmp
  start="$(process_start_time "$$")"; [ -n "$start" ] || return 1
  tmp="${LAUNCHER_IDENTITY_FILE}.tmp.$$"
  (umask 077; printf 'pid=%s\nprocess_start_time=%s\neffective_uid=%s\ncwd=%s\nlauncher_path=%s\n' \
    "$$" "$start" "$LAUNCHER_UID" "$(readlink -f "$BASE_DIR")" "$(readlink -f "$0")" > "$tmp")
  mv -f "$tmp" "$LAUNCHER_IDENTITY_FILE"
  OWNED_LAUNCHER_START="$start"
}

remove_owned_launcher_identity() {
  local pid="" start=""
  [ -n "${OWNED_LAUNCHER_START:-}" ] || return 0
  if read_launcher_identity; then pid="$LAUNCHER_RECORD_PID"; start="$LAUNCHER_RECORD_START"; fi
  [ "$pid" = "$$" ] && [ "$start" = "$OWNED_LAUNCHER_START" ] && rm -f "$LAUNCHER_IDENTITY_FILE"
}

pid_is_listener() {
  local expected="$1" pid
  while IFS= read -r pid; do
    [ "$pid" = "$expected" ] && return 0
  done < <(port_pids)
  return 1
}

import_handoff_state() {
  local key value count=0 version=""
  declare -A seen=()
  [ -f "$HANDOFF_STATE_FILE" ] && [ ! -L "$HANDOFF_STATE_FILE" ] || return 1
  [ "$(stat -c%u "$HANDOFF_STATE_FILE" 2>/dev/null || true)" = "$LAUNCHER_UID" ] || return 1
  [ "$(stat -c%a "$HANDOFF_STATE_FILE" 2>/dev/null || true)" = 600 ] || return 1
  while IFS='=' read -r key value; do
    [ -n "$key" ] && [ -z "${seen[$key]:-}" ] || return 1
    case "$key" in
      SRA_BOOTSTRAP_STATE_VERSION) version="$value" ;;
      SRA_BOOTSTRAP_HANDOFF_KEY_ID) : ;;
      REQUIREMENT_HANDOFF_API_BASE_URL|REQUIREMENT_HANDOFF_ALLOW_INSECURE_LOCALHOST|REQUIREMENT_HANDOFF_LOGICAL_PRINCIPAL|REQUIREMENT_HANDOFF_OUTPUT_ROOT|REQUIREMENT_HANDOFF_CREDENTIAL_ENV|REQUIREMENT_HANDOFF_CREDENTIAL)
        printf -v "$key" '%s' "$value"; export "$key" ;;
      *) return 1 ;;
    esac
    seen[$key]=1; count=$((count + 1))
  done < "$HANDOFF_STATE_FILE"
  [ "$count" -eq 8 ] && [ "$version" = 1 ]
}

worker_identity_file() {
  case "$1" in schedule) printf '%s' "$SCHEDULE_IDENTITY_FILE";; handoff) printf '%s' "$HANDOFF_IDENTITY_FILE";; *) return 1;; esac
}

worker_process_matches() {
  local role="$1" pid="$2" start="$3" cmd cwd expected
  process_is_live "$pid" || return 1
  [ "$(process_start_time "$pid")" = "$start" ] || return 1
  [ "$(process_effective_uid "$pid")" = "$LAUNCHER_UID" ] || return 1
  cwd="$(readlink -f "/proc/$pid/cwd" 2>/dev/null || true)"
  [ "$cwd" = "$(readlink -f "$BASE_DIR")" ] || return 1
  cmd="$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null || true)"
  expected="$role-worker"
  [[ "$cmd" == *"requirement_scheduler.cli"* && "$cmd" == *"$expected"* ]]
}

reclaim_worker() {
  local role="$1" file key value record_role="" pid="" start="" count=0 deadline
  file="$(worker_identity_file "$role")"
  [ -e "$file" ] || return 0
  [ -f "$file" ] && [ ! -L "$file" ] && [ "$(stat -c%u "$file" 2>/dev/null || true)" = "$LAUNCHER_UID" ] || {
    echo "[run_sra_api] Invalid $role worker identity record; refusing startup." >&2; return 1; }
  while IFS='=' read -r key value; do
    count=$((count + 1)); case "$key" in role) record_role="$value";; pid) pid="$value";; process_start_time) start="$value";; *) return 1;; esac
  done < "$file"
  [ "$count" -eq 3 ] && [ "$record_role" = "$role" ] && [[ "$pid" =~ ^[0-9]+$ ]] && [[ "$start" =~ ^[0-9]+$ ]] || return 1
  if ! process_is_live "$pid"; then rm -f "$file"; return 0; fi
  worker_process_matches "$role" "$pid" "$start" || {
    echo "[run_sra_api] Recorded $role worker is live but unverified; no signal sent." >&2; return 1; }
  audit "Sending SIGTERM to verified stale $role worker PID=$pid start=$start"
  kill -TERM "$pid"
  deadline=$((SECONDS + SHUTDOWN_TIMEOUT_SECONDS))
  while [ "$SECONDS" -lt "$deadline" ] && process_is_live "$pid"; do sleep 0.1; done
  if process_is_live "$pid"; then
    worker_process_matches "$role" "$pid" "$start" || return 1
    audit "Sending SIGKILL to verified stale $role worker PID=$pid start=$start"; kill -KILL "$pid"
  fi
  rm -f "$file"
}

write_worker_identity() {
  local role="$1" pid="$2" file start tmp
  file="$(worker_identity_file "$role")"; start="$(process_start_time "$pid")"; [ -n "$start" ] || return 1
  tmp="${file}.tmp.$$"; (umask 077; printf 'role=%s\npid=%s\nprocess_start_time=%s\n' "$role" "$pid" "$start" > "$tmp")
  mv -f "$tmp" "$file"
}

identity_record_matches() {
  local pid="$1" start="$2" key value record_pid="" record_start="" record_port="" count=0
  [ -f "$API_IDENTITY_FILE" ] && [ ! -L "$API_IDENTITY_FILE" ] || return 1
  [ "$(stat -c%u "$API_IDENTITY_FILE" 2>/dev/null || true)" = "$LAUNCHER_UID" ] || return 1
  while IFS='=' read -r key value; do
    count=$((count + 1))
    case "$key" in
      api_pid) record_pid="$value" ;;
      api_start_time) record_start="$value" ;;
      port) record_port="$value" ;;
      *) return 1 ;;
    esac
  done < "$API_IDENTITY_FILE"
  [ "$count" -eq 3 ] && [ "$record_pid" = "$pid" ] && [ "$record_start" = "$start" ] && [ "$record_port" = "$PORT" ]
}

runtime_title_matches() {
  local pid="$1" cmd="$2" prefix suffix title_port title_pid title_host model
  prefix="SRA-API | port="
  [[ "$cmd" == "$prefix"* ]] || return 1
  suffix="${cmd#"$prefix"}"
  title_port="${suffix%% | *}"
  [ "$suffix" != "$title_port" ] || return 1
  suffix="${suffix#* | }"
  if [[ "$suffix" == pid=* ]]; then
    model=""
  else
    model="${suffix%% | *}"
    [ -n "$model" ] && [ "$suffix" != "$model" ] || return 1
    suffix="${suffix#* | }"
  fi
  [[ "$suffix" == pid=*" | "* ]] || return 1
  title_pid="${suffix#pid=}"
  title_pid="${title_pid%% | *}"
  title_host="${suffix#* | }"
  [[ "$title_port" =~ ^[0-9]+$ ]] || return 1
  [[ "$title_pid" =~ ^[0-9]+$ ]] || return 1
  [ "$title_port" = "$PORT" ] && [ "$title_pid" = "$pid" ] && [ "$title_host" = "$RUNTIME_HOSTNAME" ]
}

is_expected_sra_api() {
  local pid="$1" cmd cwd start identity=""
  [ -r "/proc/$pid/cmdline" ] || return 1
  cmd="$(tr '\0' ' ' < "/proc/$pid/cmdline")"
  cmd="${cmd% }"
  cwd="$(readlink -f "/proc/$pid/cwd" 2>/dev/null || true)"
  [ "$cwd" = "$(readlink -f "$BASE_DIR")" ] || return 1
  [ "$(process_effective_uid "$pid")" = "$LAUNCHER_UID" ] || return 1
  pid_is_listener "$pid" || return 1
  start="$(process_start_time "$pid")"
  [ -n "$start" ] || return 1
  if identity_record_matches "$pid" "$start"; then
    identity="launcher-record"
  elif [[ "$cmd" == *"uvicorn"* ]] && [[ "$cmd" == *"api.main:app"* ]] &&
       [[ "$cmd" == *"--port $PORT"* || "$cmd" == *"--port=$PORT"* ]]; then
    identity="startup-argv"
  elif runtime_title_matches "$pid" "$cmd"; then
    identity="runtime-title"
  else
    return 1
  fi
  VERIFIED_IDENTITY="$identity"
}

port_pids() {
  lsof -t -nP -iTCP:"$PORT" -sTCP:LISTEN 2>/dev/null | sort -u || true
}

inspect_port() {
  local pids pid cmd cwd start deadline remaining
  declare -A verified_start=()
  pids="$(port_pids)"
  [ -n "$pids" ] || { audit "Port $PORT is free"; return 0; }

  audit "Port $PORT collision detected"
  lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >> "$KILL_AUDIT_LOG" 2>&1 || true
  lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >&2 2>/dev/null || true

  for pid in $pids; do
    cmd="$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null || true)"
    cwd="$(readlink -f "/proc/$pid/cwd" 2>/dev/null || true)"
    start="$(process_start_time "$pid")"
    audit "PID=$pid start=$start cwd=$cwd cmd=$cmd"
    VERIFIED_IDENTITY=""
    if ! is_expected_sra_api "$pid"; then
      audit "ABORT unverified port owner PID=$pid; no signal sent"
      echo "[run_sra_api] Port $PORT has an unrelated or unverified owner (PID $pid); refusing to kill it." >&2
      return 1
    fi
    [ "$start" = "$(process_start_time "$pid")" ] || {
      audit "ABORT PID=$pid start time changed during verification; no signal sent"
      return 1
    }
    audit "Verified stale SRA API PID=$pid identity=$VERIFIED_IDENTITY"
    verified_start["$pid"]="$start"
  done

  for pid in $pids; do
    start="$(process_start_time "$pid")"
    if ! is_expected_sra_api "$pid" || [ -z "$start" ] || [ "$start" != "${verified_start[$pid]:-}" ]; then
      audit "ABORT port owner changed or became unverified PID=$pid before SIGTERM; no signal sent"
      return 1
    fi
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

write_api_identity() {
  local pid="$1" start tmp deadline
  deadline=$((SECONDS + 2))
  start="$(process_start_time "$pid")"
  while [ -z "$start" ] && [ "$SECONDS" -lt "$deadline" ]; do sleep 0.02; start="$(process_start_time "$pid")"; done
  [ -n "$start" ] || { audit "Unable to capture API child start time PID=$pid"; return 1; }
  tmp="${API_IDENTITY_FILE}.tmp.$$"
  umask 077
  printf 'api_pid=%s\napi_start_time=%s\nport=%s\n' "$pid" "$start" "$PORT" > "$tmp"
  mv -f "$tmp" "$API_IDENTITY_FILE"
  OWNED_API_START="$start"
}

remove_owned_api_identity() {
  local pid="${1:-}"
  [ -n "$pid" ] || return 0
  if [ "${OWNED_API_PID:-}" = "$pid" ] && [ -n "${OWNED_API_START:-}" ] &&
     identity_record_matches "$pid" "$OWNED_API_START"; then
    rm -f "$API_IDENTITY_FILE"
  fi
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
  remove_owned_api_identity "${OWNED_API_PID:-}"
  [ -z "${OWNED_SCHEDULE_PID:-}" ] || rm -f "$SCHEDULE_IDENTITY_FILE"
  [ -z "${OWNED_HANDOFF_PID:-}" ] || rm -f "$HANDOFF_IDENTITY_FILE"
  remove_owned_launcher_identity
}

handle_signal() {
  SIGNALLED=1
  cleanup
  exit 0
}
trap handle_signal INT TERM
trap cleanup EXIT

bootstrap_result="$(python -m config.deployment_bootstrap bootstrap --project-root "$BASE_DIR" --port "$PORT" 9>&-)"
case "$bootstrap_result" in
  deployment_bootstrap_state_path=*) HANDOFF_STATE_FILE="${bootstrap_result#deployment_bootstrap_state_path=}" ;;
  *) echo "[run_sra_api] Deployment bootstrap returned an invalid state path." >&2; exit 1 ;;
esac
[ -n "$HANDOFF_STATE_FILE" ] && [[ "$HANDOFF_STATE_FILE" != *$'\n'* ]] || {
  echo "[run_sra_api] Deployment bootstrap returned an invalid state path." >&2; exit 1; }
import_handoff_state || { echo "[run_sra_api] Generated Handoff state validation failed." >&2; exit 1; }

if flock -n 9; then
  write_launcher_identity
else
  if ! read_launcher_identity || ! launcher_process_matches "$LAUNCHER_RECORD_PID" "$LAUNCHER_RECORD_START"; then
    audit "ABORT launcher lock is busy but owner identity is unverified; no signal sent"
    echo "[run_sra_api] Launcher lock owner cannot be safely verified; no signal sent." >&2
    exit 1
  fi
  if [ "$LAUNCHER_RECORD_START" -gt "$INVOCATION_START_TIME" ]; then
    audit "Restart already completed by newer launcher PID=$LAUNCHER_RECORD_PID start=$LAUNCHER_RECORD_START"
    echo "[run_sra_api] Restart already completed by another contender."
    exit 0
  fi
  takeover_pid="$LAUNCHER_RECORD_PID"; takeover_start="$LAUNCHER_RECORD_START"
  if ! flock -n 8; then
    deadline=$((SECONDS + SHUTDOWN_TIMEOUT_SECONDS))
    while [ "$SECONDS" -lt "$deadline" ] && ! flock -n 8; do sleep 0.1; done
    if ! flock -n 8; then
      audit "ABORT timed out waiting for concurrent restart contender"
      echo "[run_sra_api] Concurrent restart coordination timed out; no signal sent." >&2
      exit 1
    fi
    if ! read_launcher_identity || [ "$LAUNCHER_RECORD_PID" != "$takeover_pid" ] ||
       [ "$LAUNCHER_RECORD_START" != "$takeover_start" ]; then
      audit "Restart already completed while waiting for takeover coordination"
      echo "[run_sra_api] Restart already completed by another contender."
      flock -u 8
      exit 0
    fi
  fi
  echo "[run_sra_api] Existing verified launcher detected PID=$takeover_pid."
  # Close the PID-reuse/TOCTOU window immediately before granting signal authority.
  if ! read_launcher_identity || [ "$LAUNCHER_RECORD_PID" != "$takeover_pid" ] ||
     [ "$LAUNCHER_RECORD_START" != "$takeover_start" ] ||
     ! launcher_process_matches "$takeover_pid" "$takeover_start"; then
    audit "ABORT launcher identity changed before SIGTERM; no signal sent"
    echo "[run_sra_api] Launcher identity changed before shutdown; no signal sent." >&2
    exit 1
  fi
  audit "Sending SIGTERM to verified launcher PID=$takeover_pid start=$takeover_start"
  echo "[run_sra_api] Requesting graceful restart..."
  kill -TERM "$takeover_pid"
  if flock -w "$SHUTDOWN_TIMEOUT_SECONDS" 9; then
    echo "[run_sra_api] Previous runtime stopped."
    write_launcher_identity
    TAKEOVER_COORDINATION_HELD=1
  else
    audit "ABORT verified launcher PID=$takeover_pid shutdown timed out; no escalation"
    echo "[run_sra_api] Graceful launcher shutdown timed out; no escalation or replacement attempted." >&2
    exit 1
  fi
  echo "[run_sra_api] Starting replacement runtime..."
fi

reclaim_worker schedule
reclaim_worker handoff
inspect_port

# Normal logs may be reset for a new launch. The permanent audit log is append-only.
: > "$API_LOG"
: > "$SCHEDULE_LOG"
: > "$HANDOFF_LOG"

echo "[run_sra_api] Starting API + Requirement Schedule Worker + Requirement Handoff Worker"
echo "[run_sra_api] Base directory: $BASE_DIR; port: $PORT; runtime log cap: 10 MB"

uvicorn api.main:app --host 0.0.0.0 --port "$PORT" 9>&- > >(cap_log "$API_LOG" 9>&- >/dev/null 2>&1) 2>&1 &
CHILD_PIDS+=("$!"); CHILD_NAMES+=("SRA API")
OWNED_API_PID="$!"
write_api_identity "$OWNED_API_PID"

deadline=$((SECONDS + API_READINESS_TIMEOUT_SECONDS))
while [ "$SECONDS" -lt "$deadline" ]; do
  process_is_live "$OWNED_API_PID" || { echo "[run_sra_api] API exited before readiness." >&2; exit 1; }
  if pid_is_listener "$OWNED_API_PID" && [ "$(process_start_time "$OWNED_API_PID")" = "$OWNED_API_START" ]; then break; fi
  sleep 0.1
done
pid_is_listener "$OWNED_API_PID" || { echo "[run_sra_api] API readiness timed out." >&2; exit 1; }

WORKER_BOOTSTRAP='from config.bootstrap import bootstrap_env; bootstrap_env(); import sys; from requirement_scheduler.cli import main; raise SystemExit(main([sys.argv[1]]))'
python -c "$WORKER_BOOTSTRAP" schedule-worker 9>&- > >(cap_log "$SCHEDULE_LOG" 9>&- >/dev/null 2>&1) 2>&1 &
CHILD_PIDS+=("$!"); CHILD_NAMES+=("Requirement Schedule Worker")
OWNED_SCHEDULE_PID="$!"; write_worker_identity schedule "$OWNED_SCHEDULE_PID"
python -c "$WORKER_BOOTSTRAP" handoff-worker 9>&- > >(cap_log "$HANDOFF_LOG" 9>&- >/dev/null 2>&1) 2>&1 &
CHILD_PIDS+=("$!"); CHILD_NAMES+=("Requirement Handoff Worker")
OWNED_HANDOFF_PID="$!"; write_worker_identity handoff "$OWNED_HANDOFF_PID"
[ "${TAKEOVER_COORDINATION_HELD:-0}" -eq 0 ] || { flock -u 8; TAKEOVER_COORDINATION_HELD=0; }

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
