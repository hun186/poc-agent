#!/usr/bin/env bash
# SRAF OFF-1 read-only diagnostic launcher for deployed Linux hosts.
# Run with: bash run_sraf_airgap_off1_diagnose.sh
set -euo pipefail

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
cd -- "$PROJECT_ROOT"

# Both active database probes require explicit operator choices.
# No CLI-supplied credentials; these are read only from dedicated env values.
# Permit each known flag at most once; reject all others before launching Python.
DIAGNOSTIC_OPTIONS=()
SEEN_ES=0
SEEN_SQL=0
SEEN_NO_NETWORK=0
for option in "$@"; do
  case "$option" in
    --probe-es-tls-mapping)
      if [[ "$SEEN_ES" -ne 0 ]]; then
        printf '%s\n' 'ERROR: duplicate diagnostic option.' >&2
        exit 2
      fi
      SEEN_ES=1
      DIAGNOSTIC_OPTIONS+=(--probe-es-tls-mapping)
      ;;
    --no-network)
      if [[ "$SEEN_NO_NETWORK" -ne 0 ]]; then
        printf '%s\n' 'ERROR: duplicate diagnostic option.' >&2
        exit 2
      fi
      SEEN_NO_NETWORK=1
      DIAGNOSTIC_OPTIONS+=(--no-network)
      ;;
    --probe-sql-read)
      if [[ "$SEEN_SQL" -ne 0 ]]; then
        printf '%s\n' 'ERROR: duplicate diagnostic option.' >&2
        exit 2
      fi
      SEEN_SQL=1
      DIAGNOSTIC_OPTIONS+=(--probe-sql-read)
      ;;
    *)
      printf '%s\n' 'Usage: bash run_sraf_airgap_off1_diagnose.sh [--no-network] [--probe-es-tls-mapping] [--probe-sql-read]' >&2
      exit 2
      ;;
  esac
done

# Refuse contradictory requests before invoking Python or reading credentials.
if [[ "$SEEN_NO_NETWORK" -ne 0 && ( "$SEEN_ES" -ne 0 || "$SEEN_SQL" -ne 0 ) ]]; then
  printf '%s\n' 'ERROR: --no-network cannot combine with credentialed SQL/ES probes.' >&2
  exit 2
fi

# Keep the project-local default. Operators on shared/group-writable mounts
# may select another existing trusted ancestor, but cannot disable the
# Python no-follow/UID/mode validation or use a relative path.
OUTPUT_DIR="$PROJECT_ROOT/sraf-acceptance-results"
if [[ ${SRAF_OFF1_OUTPUT_DIR+x} ]]; then
  OUTPUT_DIR="$SRAF_OFF1_OUTPUT_DIR"
  if [[ -z "$OUTPUT_DIR" || "$OUTPUT_DIR" != /* || "$OUTPUT_DIR" == *[[:cntrl:]]* ]]; then
    printf '%s\n' 'ERROR: SRAF_OFF1_OUTPUT_DIR must be an absolute single-line path.' >&2
    exit 2
  fi
fi

# Use the already installed SRAF application Python environment.
# Override only when needed: SRAF_PYTHON=/path/to/venv/bin/python bash ...
PYTHON_BIN="${SRAF_PYTHON:-python}"
if ! command -v -- "$PYTHON_BIN" >/dev/null 2>&1; then
  printf '%s\n' 'ERROR: SRAF Python is not available. Activate the SRAF environment or set SRAF_PYTHON.' >&2
  exit 127
fi

exec "$PYTHON_BIN" tools/sraf_airgap_off1_hub.py \
  --suite diagnose \
  --output-dir "$OUTPUT_DIR" \
  "${DIAGNOSTIC_OPTIONS[@]}"
