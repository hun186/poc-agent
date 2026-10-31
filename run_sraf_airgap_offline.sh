#!/usr/bin/env bash
# OFF-3 partial operator dispatcher: routes only previously verified, non-mutating modes.
set -euo pipefail

if [[ "$#" -gt 1 || ( "$#" -eq 1 && -z "$1" ) ]]; then
  printf '%s\n' 'Usage: bash run_sraf_airgap_offline.sh [quick|diagnose|no-network|release-files]' >&2
  exit 2
fi
MODE="${1:-quick}"
case "$MODE" in
  quick|diagnose|no-network|release-files) ;;
  --help|-h)
    printf '%s\n' 'Usage: bash run_sraf_airgap_offline.sh [quick|diagnose|no-network|release-files]'
    exit 0
    ;;
  *)
    printf '%s\n' 'ERROR: unsupported mode; Acceptance/Upgrade/Restore are not implemented.' >&2
    exit 2
    ;;
esac

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
cd -- "$PROJECT_ROOT"

# Reuse authoritative existing entrypoints; never build a second probe path.
case "$MODE" in
  diagnose)
    exec bash "$PROJECT_ROOT/run_sraf_airgap_off1_diagnose.sh"
    ;;
  no-network)
    exec bash "$PROJECT_ROOT/run_sraf_airgap_off1_diagnose.sh" --no-network
    ;;
  release-files)
    exec bash "$PROJECT_ROOT/run_sraf_airgap_off2_verify.sh"
    ;;
esac

# Quick is a narrow, anonymous existing OFF-1 hub mode; no SQL/ES Basic,
# report submission or service restart. The Python dirfd controls all writes.
OUTPUT_DIR="$PROJECT_ROOT/sraf-acceptance-results"
if [[ ${SRAF_OFF1_OUTPUT_DIR+x} ]]; then
  OUTPUT_DIR="$SRAF_OFF1_OUTPUT_DIR"
  if [[ -z "$OUTPUT_DIR" || "$OUTPUT_DIR" != /* || "$OUTPUT_DIR" == *[[:cntrl:]]* ]]; then
    printf '%s\n' 'ERROR: SRAF_OFF1_OUTPUT_DIR must be an absolute single-line path.' >&2
    exit 2
  fi
fi
PYTHON_BIN="${SRAF_PYTHON:-python}"
if ! command -v -- "$PYTHON_BIN" >/dev/null 2>&1; then
  printf '%s\n' 'ERROR: SRAF Python is not available.' >&2
  exit 127
fi
exec "$PYTHON_BIN" tools/sraf_airgap_off1_hub.py \
  --suite quick \
  --output-dir "$OUTPUT_DIR"
