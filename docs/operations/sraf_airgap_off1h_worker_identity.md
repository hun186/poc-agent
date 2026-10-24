# SRAF OFF-1H — Schedule/Handoff Linux process identity (partial only)

OFF-1H integrates the **existing** deployment E2E `operator_e2e.requirement_e2e_support.verify_worker_identity` into the OFF-1D operator readiness matrix, without importing or starting workers, querying SQL, reading leases, delivering jobs, running an Agent, or generating reports. This is **not** a worker-health, scheduling-liveness or lease-ownership acceptance test.

From the **running deployed repository root**:

```bash
# Default: no extra Worker /proc inspection
python tools/sraf_airgap_off1d_readiness_matrix.py

# Explicit read-only local Worker process identity verification; no network required
python tools/sraf_airgap_off1d_readiness_matrix.py --probe-worker-identities
```

The separate flag is **not** dependent on `--probe-network`; it merely inspects two fixed existing launcher identity files under the selected repository root:

- `.run_sra_api_schedule.identity`
- `.run_sra_api_handoff.identity`

Files are expected to be normal files, owned by the same Linux effective UID as the operator, bounded to 256 bytes; symlinks, directories, missing/oversized files and inaccessible /proc evidence produce `SKIP` rather than inventing a worker status. Existing canonical code checks record role, PID, /proc start tick, effective UID, resolved working directory and role-specific `requirement_scheduler.cli schedule-worker` / `handoff-worker` command. The two roles must not return the same PID. The operator report never discloses PID, command line, path, user ID, start tick or exception text; only fixed status/reason and a dependency list are emitted.

**PASS means both role-specific local process identities were observed to match the existing launcher evidence, in sequence.** It does *not* prove that either worker has progressed since the observation, is polling on schedule, owns the right SQL lease, has durable DB access, is free from deadlock, runs correct code, has processed a report, or is under the correct launcher lock. The API lifespan Report Job worker is a distinct third execution path and is not observed here. `WORKERS` changes its observation aspect to `schedule_handoff_process_identity_only`; `feature_acceptance` stays `NOT_TESTED`, and `WORD` and physical `ISOLATION` remain `NOT_TESTED`. Existing graph hints `API-HEALTH` and `SQL-READ` are **informational ordering links**, not evidence dependencies for the local PID check.

Unverifiable local identities yield `SKIP`, not automatic `FAIL` and never `PASS`. Linux /proc and launcher identity files are prerequisites; Windows/macOS and separate Docker PID/file namespaces safely skip. No shell, process signals, network sockets, SQL transactions, file changes, or PID discovery are performed.

Hosted CI tests use deterministic stubs and fake identity files; green tests do not certify the user's actual Linux deployment. The next logical security-reviewed slice must independently verify SQL-backed Schedule/Handoff lease or progress evidence and the API Report Job worker, without promoting process-identity alone to FULL_LIVE.

## Formal Codex P2 remediation — shared canonical verification

The first formal Codex review identified two trust-boundary defects in the preexisting canonical helper reused by OFF-1H. These have been fixed in `operator_e2e/requirement_e2e_support.py`, so independent E2E callers also benefit.

1. **Identity file race / FIFO**: bounded checks are now performed on an already opened descriptor, obtained relative to a no-follow directory descriptor and with `O_NOFOLLOW|O_NONBLOCK|O_CLOEXEC`. `fstat()` confirms the opened inode is a regular file, is owned by the operator effective UID and is 1–256 bytes; the same descriptor reads at most 257 bytes. This prevents unchecked subsequent `Path.read_text()` from following a replaced symlink, opening a FIFO forever or consuming an oversized file.
2. **Forged process role arguments**: the verifier now parses a bounded NUL-delimited `/proc/<pid>/cmdline` instead of searching substrings in flattened argv. Only an exact `python -c` bootstrap matching the `run_sra_api.sh` launcher, or supported `python -m requirement_scheduler.cli` invocation, with the role command in its exact position and no extra args, can satisfy the identity proof. It still requires the recorded PID/start time, effective UID and cwd, and checks the start tick again after reading argv.

These checks improve process identification, but cannot certify immutable binary source, scheduler progress, SQL lease ownership or a malicious same-UID process that deliberately impersonates every allowed bootstrap attribute. This remains partial, local, read-only deployment evidence.
