#!/usr/bin/env bash
# SRAF L0/L1/L2/L3 operator diagnostics, explicit gated probes only.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "$0")" && pwd -P)"
cd -- "$ROOT"
PYTHON_BIN="python"
if [[ -v SRAF_PYTHON && -n "$SRAF_PYTHON" ]]; then PYTHON_BIN="$SRAF_PYTHON"; fi
exec "$PYTHON_BIN" "$ROOT/tools/sraf_operator_diagnostics.py" "$@"
