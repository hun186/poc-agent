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
    --probe-sql-read)
      if [[ "$SEEN_SQL" -ne 0 ]]; then
        printf '%s\n' 'ERROR: duplicate diagnostic option.' >&2
        exit 2
      fi
      SEEN_SQL=1
      DIAGNOSTIC_OPTIONS+=(--probe-sql-read)
      ;;
    *)
      printf '%s\n' 'Usage: bash run_sraf_airgap_off1_diagnose.sh [--probe-es-tls-mapping] [--probe-sql-read]' >&2
      exit 2
      ;;
  esac
done

# Use the already installed SRAF application Python environment.
# Override only when needed: SRAF_PYTHON=/path/to/venv/bin/python bash ...
PYTHON_BIN="${SRAF_PYTHON:-python}"
if ! command -v -- "$PYTHON_BIN" >/dev/null 2>&1; then
  printf '%s\n' 'ERROR: SRAF Python is not available. Activate the SRAF environment or set SRAF_PYTHON.' >&2
  exit 127
fi

exec "$PYTHON_BIN" tools/sraf_airgap_off1_hub.py \
  --suite diagnose \
  --output-dir "$PROJECT_ROOT/sraf-acceptance-results" \
  "${DIAGNOSTIC_OPTIONS[@]}"
