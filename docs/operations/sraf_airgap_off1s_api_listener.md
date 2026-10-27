# OFF-1S — operator-gated Linux SRAF API listener identity

OFF-1S is an **additional partial** operator diagnostic for the \`run_sra_api.sh\`-managed API process, not a new API route or a full E2E/airgap claim. The older OFF-1Q/R modes already sent an owner-scoped bearer token to a fixed 127.0.0.1 port but did not attest which process owned that port. OFF-1S adds optional \`--probe-api-listener\`. **When it is selected, no token-bearing Report Job GET may proceed without a matching verified listener snapshot, and the same identity must be rechecked after TCP connect and before sending Authorization and again after reading the response.**

## Authorized use

From the real deployed repository root on the **same host and PID + network namespace** as the SRAF API, set the existing OFF-1G restricted SQL credentials, canonical \`SRAF_OFF1L_SCHEDULE_ID\`, approved \`SRAF_OFF1P_ARTIFACT_ROOT\`, local numeric \`SRAF_OFF1Q_REPORT_API_PORT\` matching launcher PORT, and owner-authorized \`SRAF_OFF1Q_REPORT_JOB_READ_TOKEN\` (REPORT_JOB_READ only; never pass the token as CLI argv). Do not enable the probe on unrelated hosts or untrusted namespaces.

\`\`\`sh
python tools/sraf_airgap_off1d_readiness_matrix.py \
  --probe-network --probe-sql-read --probe-worker-identities \
  --probe-schedule-claim --probe-schedule-link --probe-handoff-ack \
  --probe-report-checkpoint --probe-docx-bytes --probe-report-live \
  --probe-report-chain --probe-api-listener
\`\`\`

All **eleven** explicit opt-ins and prior actual \`DOCX-BYTES: PASS\` are required for \`API-LISTENER\` to attempt attestation. The matrix adds a new \`API-LISTENER\` row; absent flags return NOT_TESTED, prior failure yields SKIP, and a mismatched/reused/unknown listener yields SKIP. If \`--probe-api-listener\` was requested and identity cannot be attested, \`REPORT-LIVE\` and \`REPORT-CHAIN\` are **blocked** from sending credentials. They use OFF-1S's guard passed through OFF-1Q's single bounded authenticated TCP GET, evaluated *on the already connected socket, before writing the HTTP request containing Authorization*. A second guard after complete bounded HTTP response rejects a switched listener; no token, PID, command line, API response, absolute path or socket inode appears in report JSON.

The checker opens exact repository-root launcher record \`.run_sra_api_api.identity\` by an fd pinned through O_NOFOLLOW on every ancestor and a nofollow regular-file read, requiring effective-UID ownership and a three-key exact \`api_pid\`, \`api_start_time\`, \`port\` record. It correlates proc start ticks (protects PID reuse), effective UID, \`/proc/<pid>/cwd\` directory inode/device, launcher-expected exact \`uvicorn api.main:app --host 0.0.0.0 --port <port>\` argv, the matching unique IPv4 loopback or wildcard LISTEN socket inode from \`/proc/net/tcp\`, and the PID's fd ownership of the same socket. Conflicting IPv6 listeners, unavailable proc permissions, alternate uvicorn invocation/title, multiple socket inodes, unavailable PID namespace, malformed/missing record or runtime changes are fail-closed SKIP. Bound /proc reads and FD scans; no signals, processes spawned or files altered.

## Scope limitations

This is **process identity corroboration, not cryptographic server authentication**. A malicious process with the *same UID* and filesystem permissions may be able to forge launcher records or invoke a matching command line. Checks are time-separated: a listener might be replaced in the window after the pre-send check and before transmission. No currently available snapshot constitutes an unforgeable binding between TCP session and service process. For a stronger trust model, use mutually authenticated transport or a protected Unix-domain socket with SO_PEERCRED, developed and reviewed separately.

Normal SRAF launcher binds \`0.0.0.0\`; OFF-1S does not claim network isolation or TLS from this socket observation. A \`0.0.0.0\` listener means external reachability still requires independent firewall/network-isolation validation. This check does not establish Report Job artifact provenance, Agent/LLM/ES execution or entire batch success. Prior OFF-1P/Q/R partial checks and \`feature_acceptance=NOT_TESTED\`, overall INCOMPLETE remain. Hosted CI uses synthetic /proc, identity files and fake HTTP sockets, **not** live private API/SQL/airgapped deployment.


## 2026-10-27 Codex P2 hardening

The listener process matcher accepts the launcher-issued six-argument direct
\`uvicorn\` command, the actual seven-argument Linux Python shebang +
\`/path/to/uvicorn\` console script, and the \`SRA-API | port=... |
[model | ]pid=... | hostname\` title created by the repository's
\`sra_api/core/proctitle.py\`. All variants must still satisfy the PID start
tick, effective UID, exact working directory, launcher identity and port/socket
requirements. Unrelated applications, arbitrary \`python -m\` invocations and
incorrect PID/port/title are rejected.

A unique \`/proc/net/tcp\` socket inode alone is not a unique *owner*:
another process may inherit/receive the listening descriptor and accept
the credential-bearing connection. The verifier now additionally performs
a bounded host \`/proc/*/fd\` scan and requires the matching listening socket
to be held **only by the recorded API PID**. Shared socket ownership, process
visibility restrictions, permission-denied descriptor tables or capped scans
return \`SKIP\` rather than transmitting the bearer token. The operator must
have enough process-inspection rights to make a positive claim; restricted
normal user environments may remain SKIP, rather than producing a false PASS.

This does not prove visibility of host processes hidden outside the current
PID namespace, a race-free session-to-process binding, an unforgeable
same-UID identity record or full air-gap isolation. An operator must verify
PID and network namespace visibility and appropriate host \`/proc\` permissions
before relying on any partial PASS. Hosted synthetic regressions cover shared
listener owners and realistic launch/title variants; they are not a live
production attestation.
