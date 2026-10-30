# Backlog

## Current Summary

### Release gates for PR #328 (not yet merged)

- Revalidate exact current GitHub PR HEAD, Hosted Python focused/Report Job Worker/startup tests, cross-process Linux epoch regressions and **19 OFF-0 schema-only checks** after documentation compaction; complete formal Codex review on that exact HEAD. Resolve P1 memory-compaction finding with archive identity proof, reply in existing review Thread, and re-review until no actionable Findings/Threads. **Merge only upon a separate explicit user request.**
- Cross-process plan fencing remains **same Linux host, UID, canonical repo, shared lock mount/tempdir**. Explicitly validate the actual deployment's API Worker/container topology, UID, project path and mount namespace before relying on it. New plan admissions must fail closed after another Worker's new generation; do not claim a durable or distributed shared Plan.

### Real deployment acceptance (all NOT TESTED by Hosted synthetic CI)

- Obtain separately authorized read-only Linux baseline evidence before any mutating test: `tools/sraf_runtime_baseline_readonly.py --project-root "$PWD" --api-port 9002`, verified launcher process/socket identity, `/healthz`, Schedule/Handoff Worker identity under idle versus controlled Ollama contention. Never restart services or trigger production jobs as incidental diagnostics.
- Independently verify real Ollama/LiteLLM/smolagents/ES client timeout behavior, retries and non-cancelable SDK calls under controlled busy workload. Cooperative 540s deadline and `RUNNING_OVERDUE` cannot hard-stop a blocked SDK. Observe actual report >300s stage accounting, field-selector fallback quality and endpoint saturation.
- Operator-approved strict Elasticsearch HTTPS TLS/CA/IP SAN/Mapping/index selector and exact dedicated fixture read/create-only repair; ensure no overlap with production indexes, no unsafe alias wildcard, no silent source drift or out-of-band write. WARN-only Docker IP-SAN is **not** release acceptance.
- Independently verify SQL Server schema v4 migration/rollback, service-privilege least privilege, Product Task CAS/idempotency, Schedule/Handoff claim/renewal/ownership/failover and real Report Job artifact DOCX root/SHA/ZIP. OFF-1G/1I/1K–R are partial independently read-only evidence, not atomic end-to-end confirmation.
- Complete authorized Requirement→Schedule/Handoff→Report Job→real Agent/LLM/Elasticsearch→DOCX E2E, OFF-2 packaging, OFF-3/4 release reporting, OFF-5 recovery and physical airgap acceptance. Keep SQL/ES mutations, schedule triggers and production model calls opt-in and isolated.

### Product/other deferred work

- Preserve Product schema v4 and immutable Requirement SQL authority, canonical cross-resource request idempotency, superuser-owned provisioning and version activation, low-level ownership fences, Snapshot CAS, draft activation, Task/Run owner isolation. Reverify historical PR #288 P2.1 against current GitHub rather than trusting old status; P2.2/UI/production HTTP/security acceptance remain separate.
- Job Task JT-1, Workflow Registry, LangGraph integration are NOT STARTED absent new evidence. Future capabilities include durable cross-host E2E Plan lease/attestation and expiry, HA/job retention/cancel/retry/webhooks, audit filtering, authorization hardening, SQL/ES lineage, and signed per-worker code provenance.
- Document risks: no hard SDK cancellation, no atomic ES fixture rollback or cross-system SQL/HTTP/file transaction, no cross-host Plan sharing, possible already-admitted E2E Job completion after later drift, external writer TOCTOU, independent containers/UIDs not covered, same-UID local hostile actors not isolated by private file.

## Recent Changes

- 2026-10-30: #324 cooperative E2E budget; #325 safe ES fixture and Linux same-host lock; #326 staged Plan publication; #327 local revalidation and pinned in-flight Plan, merged at main `7a0bd1c901016e7869efeeb101642e4c1438c691`. These Hosted CI/review successes are not real Linux acceptance.
- 2026-10-30: #328 adds same-host opaque generation rotation and stale E2E plan refusal. Initial Hosted CI #40990112694 SUCCESS (1,533 Python tests and 19 OFF-0 schema checks) on code/docs HEAD `03c526eb1df0217d7ecfb2e5e6115515c8d982fd`, but Codex **P1 documentation compaction finding** requires fresh final-head evidence. No Merge.
- Earlier OFF-1 slices #295–314 and Product reviews are preserved in complete archives; old review/CI status entries are historical.

## Archived History

- `.codex/archive/backlog.md-20261030-101300.md` — full 21,142-character pre-compaction active backlog, exact matching Git blob SHA `829147a7e4bb496be98a999efd02281a67ffed45`, independently re-fetched before rewrite.
- `.codex/archive/backlog.md-20261024-170825.md` and `.codex/archive/backlog.md-20261021-165000.md` — prior complete Product/airgap/workflow history.
- 2026-10-30 compaction per `AGENTS.md` after >20 work records: historical details remain retrievable, but active file lists only current unresolved gates.


- 2026-10-30 OFF-1U passive Linux load/topology gate: validate final Hosted CI+OFF-0/legacy Worker tests and formal Codex CLEAN before separate explicit user Merge. Then *only on operator's real Linux host* run read-only baseline `tools/sraf_runtime_baseline_readonly.py --no-network` and new `tools/sraf_linux_load_topology_readonly.py --samples 3 --interval 5` at idle and during already-running approved busy workload; collect sanitized PARTIAL_ONLY output. Verify actual multi-worker TMPDIR/UID/root/mount topology independently; never infer lock sharing from one PID. Ollama/LiteLLM/ES timeouts, dedicated fixture create-only writes, SQL/Handoff/Report Job/DOCX and FULL_LIVE remain independently permission-gated future tests.
