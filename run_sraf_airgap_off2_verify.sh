#!/usr/bin/env bash
# OFF-2 listed-runtime integrity check: no network, no package mutations.
set -euo pipefail

if [[ "$#" -ne 0 ]]; then
  printf '%s\n' 'Usage: bash run_sraf_airgap_off2_verify.sh (no arguments; set trusted digest via environment)' >&2
  exit 2
fi

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
cd -- "$PROJECT_ROOT"

# A local computed digest cannot serve as an independent release trust anchor.
# Never print the digest in diagnostics. The Python verifier revalidates it.
PIN="${SRAF_OFF2_TRUSTED_MANIFEST_SHA256:-}"
if [[ ! "$PIN" =~ ^[0-9a-f]{64}$ ]]; then
  printf '%s\n' 'SRAF_OFF2_PROVENANCE=INCOMPLETE reason=trusted_manifest_digest_not_supplied files_checked=0 scope=LISTED_FILES_ONLY_NOT_RELEASE_OR_AIRGAP_ATTESTATION'
  exit 2
fi

PYTHON_BIN="${SRAF_PYTHON:-python}"
if ! command -v -- "$PYTHON_BIN" >/dev/null 2>&1; then
  printf '%s\n' 'SRAF_OFF2_PROVENANCE=INCOMPLETE reason=application_python_unavailable files_checked=0 scope=LISTED_FILES_ONLY_NOT_RELEASE_OR_AIRGAP_ATTESTATION'
  exit 2
fi

# The Python tool owns all bounded no-follow descriptor validation.
# Do not make an untrusted fallback or auto-recompute an expected digest.
exec "$PYTHON_BIN" tools/sraf_airgap_off2_manifest_check.py \
  --expected-manifest-sha256 "$PIN"
