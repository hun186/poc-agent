#!/usr/bin/env bash
# OFF-3 partial operator dispatcher: routes only previously verified, non-mutating modes.
set -euo pipefail

if [[ "$#" -gt 1 || ( "$#" -eq 1 && -z "$1" ) ]]; then
  printf '%s\n' 'Usage: bash run_sraf_airgap_offline.sh [quick|diagnose|no-network|release-files|release-policy|release-deps|wheel-files|target-platform|runtime-deps|runtime-deps-user-site|runtime-launchers|deploy-check]' >&2
  exit 2
fi
MODE="${1:-quick}"
case "$MODE" in
  quick|diagnose|no-network|release-files|release-policy|release-deps|wheel-files|target-platform|runtime-deps|runtime-deps-user-site|runtime-launchers|deploy-check) ;;
  --help|-h)
    printf '%s\n' 'Usage: bash run_sraf_airgap_offline.sh [quick|diagnose|no-network|release-files|release-policy|release-deps|wheel-files|target-platform|runtime-deps|runtime-deps-user-site|runtime-launchers|deploy-check]'
    exit 0
    ;;
  *)
    printf '%s\n' 'ERROR: unsupported mode; Acceptance/Upgrade/Restore are not implemented.' >&2
    exit 2
    ;;
esac

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)"
cd -- "$PROJECT_ROOT"

# Reuse authoritative existing entrypoints; never build a second probe path.
case "$MODE" in
  diagnose)
    exec bash "$PROJECT_ROOT/scripts/diagnostics/run_sraf_airgap_off1_diagnose.sh"
    ;;
  no-network)
    exec bash "$PROJECT_ROOT/scripts/diagnostics/run_sraf_airgap_off1_diagnose.sh" --no-network
    ;;
  release-files)
    exec bash "$PROJECT_ROOT/scripts/diagnostics/run_sraf_airgap_off2_verify.sh"
    ;;
  wheel-files)
    # External digest is mandatory and cannot be minted from local bytes.
    PIN="${SRAF_OFF2_TRUSTED_WHEEL_MANIFEST_SHA256:-}"
    if [[ ! "$PIN" =~ ^[0-9a-f]{64}$ ]]; then
      printf '%s\n' 'SRAF_OFF2_WHEELS=INCOMPLETE reason=trusted_wheel_inventory_digest_not_supplied wheels_checked=0 scope=PINNED_WHEEL_BYTES_ONLY_NOT_DEPENDENCY_OR_AIRGAP_ATTESTATION'
      exit 2
    fi
    PYTHON_BIN="${SRAF_PYTHON:-python}"
    if ! command -v -- "$PYTHON_BIN" >/dev/null 2>&1; then
      printf '%s\n' 'SRAF_OFF2_WHEELS=INCOMPLETE reason=application_python_unavailable wheels_checked=0 scope=PINNED_WHEEL_BYTES_ONLY_NOT_DEPENDENCY_OR_AIRGAP_ATTESTATION'
      exit 2
    fi
    exec "$PYTHON_BIN" tools/sraf_airgap_off2_wheel_files.py --expected-manifest-sha256 "$PIN"
    ;;
  runtime-deps)
    # Inspect only selected Python interpreter install metadata, never import
    # target packages, run pip, connect to services or write an inventory.
    PYTHON_BIN="${SRAF_PYTHON:-python}"
    if ! command -v -- "$PYTHON_BIN" >/dev/null 2>&1; then
      printf '%s\n' '{"schema":"sraf_off2_direct_runtime_inventory_v2","status":"INCOMPLETE","reason":"application_python_unavailable","scope":"INSTALLED_DIRECT_METADATA_ONLY_NOT_VERSION_SOLVER_OR_WHEELHOUSE_ATTESTATION","transitive_closure":"NOT_TESTED","wheelhouse_compatibility":"NOT_TESTED","production_release_ready":false}'
      exit 2
    fi
    exec "$PYTHON_BIN" tools/sraf_airgap_off2_runtime_deps.py
    ;;
  runtime-deps-user-site)
    # Explicit opt-in diagnostic, separate from strict scheme-only runtime-deps.
    # Never import declared packages, run pip, or imply user-site release trust.
    PYTHON_BIN="${SRAF_PYTHON:-python}"
    if ! command -v -- "$PYTHON_BIN" >/dev/null 2>&1; then
      printf '%s\n' '{"schema":"sraf_off2_direct_runtime_user_site_inventory_v1","status":"INCOMPLETE","reason":"application_python_unavailable","scope":"SCHEME_PLUS_ACTIVE_USER_SITE_METADATA_ONLY_NOT_DEPLOYMENT_ATTESTATION","transitive_closure":"NOT_TESTED","wheelhouse_compatibility":"NOT_TESTED","production_release_ready":false}'
      exit 2
    fi
    exec "$PYTHON_BIN" tools/sraf_airgap_off2_user_site.py
    ;;
  deploy-check)
    # One-command local passive observation; stdout-only, no output-dir,
    # network, credentials, package installs or service/worker mutation.
    PYTHON_BIN="${SRAF_PYTHON:-python}"
    if ! command -v -- "$PYTHON_BIN" >/dev/null 2>&1; then
      printf '%s\n' 'SRAF_DEPLOY_CHECK=INCOMPLETE reason=application_python_unavailable'
      exit 2
    fi
    exec "$PYTHON_BIN" tools/sraf_local_deploy_quickcheck.py
    ;;
  runtime-launchers)
    # Passive current-shell PATH and uvicorn script shebang only.
    # NO process introspection, service startup, live imports, or credentials.
    PYTHON_BIN="${SRAF_PYTHON:-python}"
    if ! command -v -- "$PYTHON_BIN" >/dev/null 2>&1; then
      printf '%s\n' '{"schema":"sraf_off2_static_launcher_interpreter_v1","scope":"CURRENT_SHELL_PATH_AND_UVICORN_SCRIPT_ONLY_NOT_RUNNING_SERVICE","status":"INCOMPLETE","reason":"application_python_unavailable","api_worker_runtime_verified":false,"running_process_verified":false,"production_release_ready":false}'
      exit 2
    fi
    exec "$PYTHON_BIN" tools/sraf_airgap_off2_runtime_launchers.py
    ;;
  target-platform)
    # No credentials, network, external binaries or environment mutation.
    # The Python ABI reported is precisely the selected SRAF Python runtime.
    PYTHON_BIN="${SRAF_PYTHON:-python}"
    if ! command -v -- "$PYTHON_BIN" >/dev/null 2>&1; then
      printf '%s\n' '{"schema":"sraf_off2_linux_target_inventory_v3","status":"INCOMPLETE","reason":"application_python_unavailable","scope":"TARGET_IDENTITY_ONLY_NOT_PACKAGE_OR_AIRGAP_ATTESTATION","full_live":"NOT_TESTED","production_release_ready":false}'
      exit 2
    fi
    exec "$PYTHON_BIN" tools/sraf_airgap_off2_linux_target.py
    ;;
  release-policy|release-deps)
    # OFF-2 local-only advisory modes. Neither may install, sign,
    # fetch dependencies, write evidence or imply airgap acceptance.
    PYTHON_BIN="${SRAF_PYTHON:-python}"
    if ! command -v -- "$PYTHON_BIN" >/dev/null 2>&1; then
      printf '%s\n' 'ERROR: SRAF Python is not available.' >&2
      exit 127
    fi
    if [[ "$MODE" == "release-policy" ]]; then
      exec "$PYTHON_BIN" tools/sraf_airgap_off2_policy_coverage.py
    fi
    exec "$PYTHON_BIN" tools/sraf_airgap_off2_requirements_audit.py
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
