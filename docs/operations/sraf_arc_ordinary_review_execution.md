# Ordinary A8 trusted execution bridge

The internal ask_with_report keyword-only parameters _arc_review_policy and
_arc_review_deadline_monotonic are for trusted server-side callers only.
They pass to run_data_agent and are bound only during a report-mode Data Agent
invocation; the deadline must already reserve generation time. The existing
per-tool instance propagation restores the private scope on worker threads,
not in public/model tool inputs. A missing or mismatched original question,
invalid deadline, absent callback or closed execution does not supply a grant.
The callback receives the exact final-refill scope and still must enforce
current authenticated owner, source ACL, question/date, endpoint/model/CA
and egress policy. No production caller or owner ACL is installed here.

The lifetime is closed on normal return or exception; late tool invocations
cannot renew it. A policy that denies or loses lifetime during authorization
cannot authorize the operation. An in-flight network request cannot be recalled.
Existing A8 scope, feature flags, transport, reservation and deadline gates
remain authoritative. The ordinary report result is unchanged, and no new
env settings are introduced. A2/A7 allocation may still consume the available
optional LLM slot before A8; unified priority scheduling is a separate task.
Synthetic tests exercise actual tool threads and final-refill binding, not
real private Elasticsearch or a model provider.
