#!/usr/bin/env bash
# SRAF OFF-1 read-only diagnostic launcher for deployed Linux hosts.
# Run with: bash run_sraf_airgap_off1_diagnose.sh
set -euo pipefail

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
cd -- "$PROJECT_ROOT"

# Use the already installed SRAF application Python environment.
# Override only when needed: SRAF_PYTHON=/path/to/venv/bin/python bash ...
PYTHON_BIN="${SRAF_PYTHON:-python}"
if ! command -v -- "$PYTHON_BIN" >/dev/null 2>&1; then
  printf '%s\n' 'ERROR: SRAF Python is not available. Activate the SRAF environment or set SRAF_PYTHON.' >&2
  exit 127
fi

exec "$PYTHON_BIN" tools/sraf_airgap_off1_hub.py \
  --suite diagnose \
  --output-dir "$PROJECT_ROOT/sraf-acceptance-results"
