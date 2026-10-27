# OFF-1S — local API launcher/listener identity (partial)

This operator-only check is opt-in. It reads the existing run_sra_api.sh launcher identity file and checks mode 0600, same UID, PID start time, repository cwd, strict uvicorn api.main:app command and live listening TCP inode/FD. It does not create processes, API routes, identities or credentials. It cannot prove cryptographic service identity or physical network isolation.

Authorized Linux operator: from the deployed project root, run the existing OFF-1R matrix command with the extra flag --probe-api-owner and existing SRAF_OFF1Q_REPORT_API_PORT. For owner-only (no SQL or Report Job token required), run:

    python tools/sraf_airgap_off1d_readiness_matrix.py --probe-network --probe-api-owner

For the full operator diagnostic, include all ten existing OFF-1R flags, plus --probe-api-owner. Prior Report Job credentials are read only under their original nine authorization flags. New API-OWNER result is NOT_TESTED by default, SKIP on uncertainty and PASS only for a matching observed launcher record, live process and socket inode. When --probe-api-owner is enabled for REPORT-LIVE/REPORT-CHAIN, failure prevents a bearer GET; each GET rechecks the PID/start/inode immediately before and after token-bearing network activity. Changed or missing identity yields SKIP.

The SRAF launcher binds 0.0.0.0 by default, so this check permits one unambiguous wildcard or exact 127.0.0.1 IPv4 LISTEN inode on the configured port, rejects competing IPv4/IPv6 listeners and unknown PID namespace; procfs must be readable from the same PID/network namespace. Strict argv matches the current launcher, so alternate launchers produce SKIP. Nothing is printed from the identity record, socket inode, process command, credentials, SQL IDs, HTTP body or exception texts.

SECURITY LIMITS: The mutable launcher record can be spoofed by a same-UID adversary. The observed process may share a socket with another process, and separate /proc snapshots cannot eliminate time-of-check/time-of-use races. Even matching pre/post tuples are not cryptographic proof of the specific receiving process; use independent authenticated service identity for stronger assurance. Hosted CI uses synthetic /proc, not a real deployment. It does not attest Agent/LLM/Elasticsearch, Word provenance, whole-batch completion or isolation. The global feature_acceptance stays NOT_TESTED.
