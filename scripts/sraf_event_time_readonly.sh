#!/usr/bin/env bash
# SRAF #393 / PR #395: run bounded, strict-TLS, GET-only news_test acceptance.
# No Mapping writes, no data mutation, no GLM, SQL or service restart.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd -- "$ROOT"
PYTHON_BIN="${SRAF_PYTHON:-python}"
# Optional deployment config from another checkout without altering any
# running service tree. No config path/credential is printed.
EXTRA=()
if [[ -n "${SRAF_CONFIG_ROOT:-}" ]]; then
  EXTRA+=(--config-root "$SRAF_CONFIG_ROOT")
fi
exec "$PYTHON_BIN" "$ROOT/tools/sraf_event_time_readonly_acceptance.py" --run "${EXTRA[@]}" "$@"
