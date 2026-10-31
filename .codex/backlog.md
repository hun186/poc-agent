# SRAF Backlog — Active Work and Historic Archive

## Current Focus — Draft PR #340, 2026-10-31

- Integrate **explicit opt-in strict ES HTTPS/CA/IP SAN and literal-index Mapping** into existing OFF-1 hub and optional one-click Bash flag `--probe-es-tls-mapping`. The default `diagnose` must not send ES credentials. Selected mode must stay bounded read-only, fail closed for missing configuration, and must not send an invalid-password credential-control challenge or relax TLS.
- Verify exact newest PR HEAD: Hosted Python hub/launcher/strict ES projection + existing OFF-1B HTTPS parser regressions, 19 OFF-0 schema-only checks, Shell syntax, full formal Codex review and zero unresolved P1/P2 or review threads. **Do not merge without separate user authorization**.
- Runtime tests on the private Linux host (ES CA file and configured literal index, SSL IP SAN, service/reverse proxy authentication, credentials, Mapping and false-response behaviors) are **NOT TESTED** by Hosted CI. Independent password authentication is not established without negative control, which requires separate authorization due account-lockout/audit risks; never claim full ES gate PASS from these partial observations.

## Pending Release and Operations Gates

- OFF-1: collect private Linux operator evidence under the actual SRAF Python environment; prove launcher/API ownership, output root parent trust and actual `/healthz`/Report Job UI; check Schedule/Handoff processes in the correct PID namespace. If the repo ancestor is group writable or symlinked, private dirfd evidence must refuse output, not disable protection.
- ES: independently validate correct CA+IP SAN and expected service, `ES_INDEX` selector/mapping compatibility, protected authentication and authenticated read-only query capability; optional fixture/source integrity and dedicated index creation require **separate explicit consent and no production overlap**. Never infer FULL_LIVE from TCP.
- SQL Server: separately validate v4 schema/migration and rollback, product/requirement SQL source authority, ODBC Driver 18 TLS identity, dedicated low-privilege SELECT-only principal, CAS/idempotency, signed/owner-scoped service keys. OFF-1G constant SELECT alone cannot prove authorized production SQL operations.
- Schedule/Handoff: validate real versions, activation, auto-claim, worker identity, lease/renew/ownership, handoff ACK/reconciliation, remote report and SQLite/job/artifact integrity under separate auth; two visible worker processes do not prove E2E.
- Agent/LLM: measure real provider contention in Ollama's potentially separate container and SRAF DataAgent stage timing under load; timeout/cooperative budget cannot forcibly terminate all blocked SDK calls; do not silently start real report Job during normal startup or diagnose. Actual Word, browser dashboard, and auth/download checks still required.
- Packaging/airgap: OFF-2 release packaging/provenance, OFF-3/4 offline release/report, OFF-5 backup/restore, physical network isolation, fully automated operator report and faithful NOT_TESTED gates. Guardrail: no synthetic/fixture/Hosted test should become an attestation of on-premises physical airgap or successful Agent+ES+SQL+DOCX chain.

## Deferred Features and Risk

- Check exact hosted state before acting on historical PR #288/P2.1 and #328 or #322 handoffs; archived discussions may be obsolete. Keep release gates anchored in current exact-HEAD evidence.
- Product Task/Requirement schema v4, immutable SQL authority and provenance, owner-scoped idempotency, snapshot/version CAS, signed worker/runner plans and service boundaries must be preserved. UI, security and production HTTP flows have separate release gates.
- JT-1 Job Task, Workflow Registry, LangGraph integration, cross-host durable E2E plan lease/attestation, HA/retention/cancel/retry/webhooks, audit filtering, SQL/ES lineage are deferred unless independently implemented and verified.
- Known limitations remain: no hard SDK call cancellation, ES fixture operations non-atomic with independent writers, no cross-system SQL/HTTP/files transaction, E2E Plan host/UID/namespace fencing only, already-admitted jobs can outlive later plan drift, and external process writers/parallel containers are outside the current local evidence model.

## Recent Outcomes

- #319 removed heavy E2E preflight from ordinary startup. #333–335 implemented actual DataAgent timings, Report Job progress and UI, subject to separate live acceptance.
- #336–339 merged with user permission: #336 authorized one real Report Job CLI; #337 one-command read-only OFF-1 hub; #338 root Bash launcher and project-local private evidence; #339 passive local Schedule/Handoff identity observation. All are **partial** probes; no automatic SQL/ES/LLM jobs from regular diagnose.
- PR #339 final `9f8a5858` Hosted #41100220011 SUCCESS (75 Python, 19 OFF-0), Codex CLEAN; squash merge `b758c2ef944ed6bedd1e63c3654291d18d30a785`. Real Linux Worker PID namespaces not yet accepted.

## Archived History

- `.codex/archive/backlog.md-20261031-031500.md`: **complete byte-identical pre-compaction backlog** (15,076 chars, Git blob SHA `56d811914d7a7c48c926baaffe78fffdef6d4c6a`), independently fetched and SHA checked before rewriting this active document. Includes historical dated requests / PR checks / findings and earlier deferred tasks; consult only when a historical handoff needs re-evaluation.
- Existing `.codex/archive/` retains older project records; current source code and live GitHub PR/CI state take precedence over archived statuses.
- 2026-10-31: compacted per AGENTS.md dated-entry threshold to keep active handoff focused without deleting historical full evidence.


- **After merged #340 — Draft #341:** current one-command SQL-01 integration requires Hosted exact-head regression for original OFF-1G strict ODBC TLS test suite and new hub/shell opt-in safety, 19 OFF-0 schema-only and formal Codex CLEAN with no unresolved threads; no Merge absent explicit user instruction. Schema v4 source/permissions verification is deliberately NOT IMPLEMENTED by this constant-read probe: design a separate bounded read-only metadata evidence query only after identifying authoritative schema contract, permitted tables, principal permissions and operator consent. On-site private SQL TLS/IP SAN, actual Driver 18/ODBC and non-cancelable timeout behavior require independent live evidence.


- **OFF-4 current focused increment:** Generate a Chinese 0600 TXT companion to the existing one-command OFF-1 JSON via fixed vocabulary only, add no new probes/secret sources, test fallback on second-file write failure and no-network behavior; require exact-head Hosted and formal Codex. Manual OFF-2 packaging/provenance, full offline deployment and OFF-5 restore remain future separate gates, not completed by a human-readable summary.


- **2026-10-31 E2E operator guard rebased task:** port old PR #322 client-side SIGALRM safety and tests onto current main without old .codex rewrite, rerun exact-head Hosted E2E/19 OFF-0 and formal review. Full server asynchronous/cancellation-safe E2E status/poll and private Linux high-load validation remain separately planned; do not treat elapsed client deadline as cancellation of ES writes.

- **OFF-4 後續診斷可讀性，2026-10-31：** 將現有 TXT 的通用建議補充為少數嚴格比對的已審查原因碼建議；不輸出原始例外或原因、不加網路/資料庫操作。增加錯配/未知/惡意型別/多項手動 Gate 保留測試；必須通過 exact HEAD Hosted CI、正式 Codex Review 才可 Merge。完成後仍需 OFF-2 套件、獨立現場 SQL/ES/LLM/Worker 與 OFF-5 還原證據。


- **2026-10-31 OFF-1 one-command output safety increment (candidate):** preserve the project-local default, add only optional `SRAF_OFF1_OUTPUT_DIR` absolute single-line env override to existing Bash wrapper, no new flags or credential paths; retain verified Python nofollow-dirfd authority. Test default/override/unsafe values and no fallback; Hosted exact-head and Codex review required. Follow-up live private Linux permission test and complete OFF-2–5 remain NOT_TESTED.


- **2026-10-31 OFF-1 root launcher socket-free candidate:** wire only existing `--no-network` Python hub mode through exact Bash allowlist; prohibit duplicate and combined SQL/ES opt-ins before Python. Verify full output to the existing safe private dir and preserved INCOMPLETE/NOT_TESTED semantics in Hosted, perform exact-head Codex Review and conditional Merge. Live physical airgap and dependencies remain pending.
