# OFF-1T — Standalone, read-only API listener observation

This is an **optional local diagnostic** for the Linux host running SRAF. It
reuses the hardened OFF-1S `probe_api_listener` attestation, including
launcher identity, PID start, EUID/cwd/argv, IPv4 listening socket, procfs
mount visibility and exclusive **per-thread** descriptor ownership.

Unlike the OFF-1S readiness-matrix `--probe-api-listener` gate, this
standalone CLI does **not** require any previous SQL, Handoff, Report Job or
DOCX flags to run. It **never** sends a bearer token, makes network requests,
starts an API, changes files, or runs a scheduled task. It is not a replacement
for the OFF-1S pre-Authorization check on the *connected socket* during a real
operator-authorized Report Job GET.

From the real installed repository (the same PID/network namespace as the API),
supply a numeric local API port matching `run_sra_api.sh` and an absolute
non-symlink deployed project directory:

```sh
python tools/sraf_airgap_off1t_api_listener_check.py \
  --project-root /your/deployed/sraf/repository --api-port 9002
python tools/sraf_airgap_off1t_api_listener_check.py \
  --project-root /your/deployed/sraf/repository --api-port 9002 --format json
```

The sample path and port are placeholders, not asserted deployment values.
Run this **locally**, with no SQL/API credential or external connectivity.
Outputs only fixed status/reason codes and non-sensitive booleans; no process
PID, file paths, socket inode, token, or raw error text.

| Exit | Status | Meaning |
| --- | --- | --- |
| 0 | PASS | Local OFF-1S listener snapshot corroborated |
| 2 | SKIP | Missing, changed, restricted or unverifiable evidence |

Even a PASS means `mode=PARTIAL_ONLY_NOT_ACCEPTANCE` and
`feature_acceptance=NOT_TESTED`. In particular, it is not authenticated
service identity, a race-free proof, physical network isolation, successful
SQL/ES/LLM/Agent execution, or a complete DOCX report acceptance.

Existing [OFF-1S operator guidance](sraf_airgap_off1s_api_listener.md)
documents procfs restrictions, same-UID impersonation and namespace risks.
On restricted systems this scan may intentionally SKIP; do **not** loosen
checks to force PASS. Use the full OFF-1S matrix and explicit safe opt-ins
for credential-bearing Report Job diagnostics only with authorized evidence.
