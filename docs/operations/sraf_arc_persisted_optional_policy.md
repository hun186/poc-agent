# Persisted claimed Job bridge for optional deep ARC policies

The explicit, still non-production execute_claimed_nround_job entrypoint
accepts two optional trusted server-side callbacks: check_frequency_scope
and check_review_egress. Their absence means no optional DF or model
transmission, even with shadow flags set. No implicit allow policy, public
request argument, or API/worker dispatch is installed.

The existing persisted Job scope reloads the exact running Job and wraps
each supplied policy. A separate same-database read transaction verifies
the original claim identity, actual sidecar lease hash, SEARCHING state
and current round before and after the external policy. The callback sees
the fresh persisted Job, immutable question scope and, for A8, exact
candidate source IDs and endpoint/model/TLS settings. The low-level
WorkerScopeBinding retains the existing per-round authorization, shared
resource budget and deadline checks. The independent callback must still
enforce actual source/document and egress permission (or broader DF
denominator permission); a live lease is not equivalent to that authority.

No database schema change, new production caller or auto-enabled feature.
A revoked lease during authorization prevents optional IO; a revocation
during an in-flight request cannot recall bytes already sent. Failed
checkpoint fencing prevents main retrieval handoff. Synthetic SQLite
and adapter tests do not establish actual deployment permissions or live
model quality. Ordinary-report A8 still requires its own authorization
and identity boundary.
