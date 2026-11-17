# SRAF Backlog — Active, 2026-11-08

## Current Focus: Advanced diagnostics subdirectory migration + private host evidence

- **#373 VERIFIED MERGED 2026-11-08** (squash `41f528d6302d86d1d67fe6b140cf416b928aa182`, exact PR head `edec19989cc7bc0cd9d63ccfa4ad809401d1364a`): moved the three advanced `run_sraf_airgap_*.sh` entrypoints to `scripts/diagnostics/`, while keeping `0_一鍵快檢_SRAF.sh` and `run_sra_api.sh` in root. Fix internal scripts' path-to-root, old command references, tests/CI and explicit release policy coverage. New `scripts/diagnostics/README.md` explains engineering-only modes. External callers of legacy root-relative advanced script paths will need updating, without hidden compatibility wrappers. Latest-head Hosted OFF-0 19, OFF-1 519, OFF-2 577, target Python3.10 496, operator E2E 83 passed; formal Codex Review completed clean with zero findings and no review threads. No private host verification.
- **After merge still pending:** private Linux operator runs unchanged zero-argument root shortcut; inspect only `SRAF_DEPLOY_CHECK_JSON=...`. Strict identity and FULL_LIVE remain NOT TESTED.

## Previous current focus: One-click already merged

- **#371 VERIFIED MERGED 2026-11-08** (squash `10691986dadb71b45ef01f7ea0f03354e3de15fb`): executable root `0_一鍵快檢_SRAF.sh` sorts first; no args runs exactly existing `deploy-check`, `--help` shows Chinese safety/readout guidance; other args rejected. Top README, operator docs, Git-reviewed explicit root file policy and subprocess tests delivered. Hosted latest-head OFF-0/1/2 Python3.10/operator fixture and formal Codex completed clean; no desktop-trust change, default mode change or new probe.
- **After reviewed merge:** actual Linux operator must still execute the shortcut and provide `SRAF_DEPLOY_CHECK_JSON=...`; no ChatGPT-hosted code review proves that private host works or that full OFF-1S/SQL/ES/LLM/Word/airgap acceptance has passed.

## Previous current focus (real private Linux observation; still open)

- #367, #368 and #369 **MERGED**. #368 squash `2330c6e263026aa438ed71ca74043729f00b64a9` decoupled passive OFF-1S from optional native SQL; #369 squash `bcd51f9aaea9072f055c8502ac0c0a74616c7d67` decoupled passive OFF-1H from optional E2E dotenv. Both exact latest heads had all Hosted CI success and formal Codex reviews completed clean with zero unresolved findings/threads.
- **Pending actual operator evidence**: execute **one command** on the running Linux checkout, `bash run_sraf_airgap_offline.sh deploy-check`, share only its final sanitized `SRAF_DEPLOY_CHECK_JSON=...` line. Do not replay six separate heredocs. The tool does not write reports, contact localhost, import target packages, authorize Bearer or execute SQL/ES/LLM/Report Job. Host runtime remains NOT TESTED in Hosted CI.
- After reviewing actual output, decide the narrowest necessary follow-up. Strict API listener exclusive-owner proof, trusted evidence directory, anonymous HTTP health, service runtime/interpreter and independently authorized SQL/ES/Agent live acceptance are **separate** checks; no automatic escalation from `PASS_PARTIAL`.

## Completed #369 candidate (historical; merged) 

- The prior lazy `python-dotenv` import candidate is complete in #369, not pending. This section preserves history without making the old candidate the current task.

## Completed #368 candidate (historical; merged)

- #367 deployment `deploy-check` is **MERGED** at `988b617d9d9327af6064ab2443dc815515b511d8`; default remains six read-only local observations with no socket-exclusivity attestation or credentials. Do not repeat manual heredocs as the recommended operator workflow.
- Candidate now: OFF-1S listener imports OFF-1P/Q, eagerly pulling optional `pyodbc` even for safe six-stage socket prerequisites. Extract existing stdlib-only nofollow root/port validation without changing semantics; allow API identity stage to remain available when `pyodbc` cannot import. Keep canonical Worker identity fail-closed without `dotenv`; do not claim Worker probe was fixed. Targeted import-denial regression plus Hosted OFF-0/1/2/operator and exact-head Codex mandatory before merge.
- After review, actual user Linux `deploy-check` result, strict nofollow report directory/POST-free health observation, and independently authorized live E2E remain open; do not grant release/production acceptance from these partial code changes.

## Previous milestone (merged #367; historical candidate language below)

- Deliver **`bash run_sraf_airgap_offline.sh deploy-check`**: one no-network/no-artifact SRAF check wrapping existing OFF-2 target-platform, active-user-site direct Metadata, static PATH launchers, OFF-1 host disk, canonical Schedule/Handoff identity and bounded API9002 six-stage listener preflight. Do NOT force the operator to copy/paste sequential heredocs. Per-check errors must not abort independent checks (native pyodbc/python-dotenv may be missing); share only sanitized fixed status/count JSON.
- Existing `quick`, `diagnose` and `no-network` modes remain unchanged. Their strict `_secure_output_dir` ancestry guard is security-critical; shared mount `output_dir_unverified` must NOT be bypassed by weakening permissions. New `deploy-check` uses stdout only, leaves report directories untouched.
- Exact newest-HEAD Hosted Python 3.10 (Ubuntu22.04) / Python3.11 OFF-2, OFF-1, operator E2E, formal Codex Review completed CLEAN and zero unresolved threads/findings are mandatory for Auto-Merge v2. Current PR #367 initial review found P1 backlog memory compaction (this archive) and P2 eager native-dependency imports; review/CI must be rerun at final head after fixes.

## Actual Operator Evidence and Limits

- Private Linux 2026-11-03: OFF-2 active user-site direct METADATA **15/15** (13 scheme +2 user-site for smolagents/pyodbc); Python/Uvicorn current-shell identities **MATCH/DIRECT_MATCH**, user-site active; Schedule/Handoff canonical recorded process identity **PASS 2/2**.
- API9002 OFF-1S full strict socket-owner proof returned `SKIP/api_listener_unverified`, but operator separately observed six cheap API identity/listener prerequisites PASS; global socket-exclusivity/recheck **NOT_TESTED**. Quickcheck must never promote six prerequisites to full listener authority.
- Existing OFF-1 `no-network` run returned `INCOMPLETE reason=output_dir_unverified` **before probes** because safe private output location could not be attested. This is not evidence the running system failed.
- Hosted synthetic PASS_PARTIAL / quickcheck passes do **not** certify running API/Report Job Python/venv/UID, worker business work, pyodbc import/ODBC18 native load, dependency version satisfaction, provider SQL/ES/LLM, or physical airgap.

## Pending Release, Operations and Security Gates

- **OFF-1:** trusted output ancestry and safely pinned evidence, API exclusive listener proof, actual `/healthz` / browser static UI and real service interpreter/UID/site only in explicitly authorized checks. Existing anonymous local probes must not be treated as API auth proof.
- **OFF-1B / ES:** correct private HTTPS CA/IP SAN, literal index Mapping, authenticated query capabilities, service identity, independent negative-control authorization; no credential guessing or unsafe host mutation.
- **SQL/ODBC:** driver 18 native/pyodbc ABI load and SQL TLS identity, least-privilege source/role authority and schema-v4 migration/rollback. OFF-1G constant SELECT is not schema authority.
- **Workers, Agent, Handoff, Report Job:** actual Schedule activation/auto-claim/lease ownership/handoff ACK, real Agent/LLM/ES contention budgets, DOCX integrity, owner-scoped API auth, Job E2E and durable recovery, separate live/operator consent. No fake results or live default probes.
- **OFF-2/3/4/5 packaging and install:** independently signed complete CPython3.10 x86_64 transitive lock/wheelhouse + ODBC/model/native resources/license, trusted pinned release manifest, isolated disconnected installation, upgrade/rollback and backup/restore, physical airgap evidence and FULL_LIVE E2E. Existing broad >= direct dependencies remain unlocked.
- Preserve product Task/Requirement v4 immutable SQL and owner scoped CAS/idempotency/audit, service keys, E2E safety/plan locks and existing Report Job queue; cross-host atomic or hard provider cancellation is NOT IMPLEMENTED. JT-1, workflow registry, LangGraph, HA/retention/cancel/retry/webhooks and SQL/ES lineage remain deferred unless independently approved.

## Recent Outcomes

- #319 decoupled expensive operator preflight from API startup; #333–339 delivered async job progress, CLI/operator OFF-1 probes and canonical Worker identities; source current GitHub and existing CI, not historical "draft" summaries.
- #365 merged opt-in user-site METADATA, #366 merged current-shell static launcher diagnostic with P2 split-venv symlink fix. Issue #290 tracks ongoing operator evidence and remaining gates.
- PR #367 adds the operator-requested one-command local deployment check. It is a **partial-only** quick diagnostic: no network, artifact writes, package installs, service restart or privileged live actions. Latest exact-head review controls merge.

## Archived History

- `.codex/archive/backlog.md-20261103-182200.md`: complete verbatim pre-compaction backlog, including all historic work/date blocks and unresolved handoffs, archived before rewriting this active file for AGENTS.md memory compaction; consult only for historical evidence.
- `.codex/archive/backlog.md-20261031-031500.md`: earlier complete pre-compaction backlog, Git blob SHA `56d811914d7a7c48c926baaffe78fffdef6d4c6a`; existing archives remain.
- Compacted 2026-11-03 after AGENTS.md dated-record threshold; full history retained in archives; current code, exact-head PR/CI and actual operator evidence supersede stale historical draft labels.

- **2026-11-09 layered diagnostics candidate:** implement/test one root L0/L1 default and explicitly selected L2 SQL/ES/local Ollama, L3 single real Report Job + DOCX (existing safe backend); full Requirement→Schedule→Handoff→Report Job E2E remains NOT_IMPLEMENTED in unified runner, pending isolated fixture, authoritative scheduler activity and separate operator consent. No real Linux test or release-ready claim until independently observed.

- **2026-11-09 full-E2E integration candidate supersedes prior NOT_IMPLEMENTED note if merged:** real L3 `--full-e2e` delegates to existing authoritative automatic-schedule E2E Harness (isolated canonical fixture, SQL mutations, real LLM/ES under deployed live mode, DOCX and cleanup). Do not claim this is merged or live validated before exact-head CI, formal review and private Linux evidence. Physical airgap, Wheelhouse lock, backup/restore, rollback remain separate pending gates.

- 2026-11-09 in-flight intranet maintainer-report candidate: add readable Chinese L0-L3 diagnosis and on-host opt-in trusted TXT+JSON, test worker-identity 0/2 interpretation and avoid false ES/LLM functionality verdict. Hosted CI/formal Codex review plus user Linux verification required before acceptance.

- **2026-11-09 maintenance entry consolidation:** user wants only one obvious root diagnostic script. First ship/review --level L0 (pure no-network) and --save-report (home-owned private TXT+JSON) through single 1_ entry; only then retire old root 0_ shortcut and update doc/tests/policy. Important: user uses one-way incremental deployment, so GitHub delete of 0_ may not remove the already-deployed file; no automatic remote deletion. Await PR Hosted CI + formal Codex and local L0/report verification.

- 2026-11-09 retirement candidate pending exact-head CI/Formal Review and private host: root legacy 0_ alias deleted from repository, canonical OFF-3 passive deploy-check intact. Have operator verify unified --level L0 and --save-report on private Linux, then if original 0_ persists due one-way sync perform deliberate one-time cleanup after confirming script is obsolete. Remaining L2/L3 real SQL/TLS/LLM/E2E tests NOT TESTED.

- **2026-11-10 P0 #393 Evidence date integration:** two concurrent PRs reconciled: #394 CLOSED without merge, #395 only OPEN/ready for review (still unmerged); #394 relevant regressions transferred to #395, no conflicting helper/schema pairs included. Run latest-head Python3.10/3.11 Evidence and full existing CI, Codex formal clean Review, and only then risk-approve GitHub merge. Private `news_test` read-only Event/Timeline nested queries, Event IDs, time zone cutoffs and report/DOCX date interpretation remain independent operator acceptance gates. Link: `docs/operations/sraf_event_date_394_395_integration.md`.

- **2026-11-10 #395 latest date-refill follow-up (candidate only):** Codex latest P2 showed widened ES legacy date filters can let out-of-range candidates exhaust the first `size` hits before Evidence verification. Canonical #395 now refills date-scoped queries via bounded `from` pages of the same ES query, re-applies full strict/relaxed Evidence builder across candidates, stops on enough valid docs, exhaust or max candidate budget. `query_meta.date_candidate_refill` and `result_incomplete` expose cap rather than false empty. Explicit day/month/year query and implicit 4-digit years participate; no-date query remains one-shot. Hosted tests, exact HEAD Codex Review and real `news_test` operator acceptance are separate; DO NOT MERGE until gate passes.

- **2026-11-10 #395 P2 search completeness across report pipeline:** Latest Codex found `result_incomplete` was lost when Data Agent rebuilt `query_meta`, and report LLM received only question/date/stats/evidence. New candidate changes propagate raw ES incomplete status through `agent/data_agent/runtime.py`, Data Agent report prompt, trace, `agent/report_agent.py`; incomplete empty searches return an explanatory non-report with zero report-LLM calls, while incomplete nonempty reports get deterministic warning + `search_status`. Tests in `tests/test_sraf_report_search_completeness.py`. Await latest head CI and independent Codex review; do not merge or declare live PASS.

- **2026-11-10 #395 live verification handoff:** Build standalone `sraf-date-readonly.zip` on Windows/CI from latest reviewed PR HEAD; transfer using existing one-way 7z/Robocopy update mechanism; extract `_sraf_date_readonly` next to SRAF and invoke `bash _sraf_date_readonly/run.sh` (no Linux Git commands). Read redacted `news_test` JSON; assess strict CA+SAN, nested Mapping, Event/Timeline/date/Evidence/paging; record PASS_PARTIAL/INCOMPLETE truthfully. Live ES, report LLM/DOCX and performance remain pending. No auto Merge #395 based only on packaging or synthetic results.


## 2026-11-12 P1 — 官方全名／通稱的語意軸去重（供使用者確認）

- **Candidate PR not merged:** `agent/es/query_terms.py` Prompt 查核官方全名↔通稱/簡稱/俗稱、等價核心詞併為一軸、無歧義的簡繁變體、共享歧義非核心別名剔除；固定案例離線測試、Python3.10/3.11 CI、正式 Review、使用者前後對照需完成。
- **Outstanding, separately scoped:** 實際 `news_test` analyzer、mapping、ES candidate retrieval and date-scoped Evidence/report recall still NOT TESTED; LLM未產生官方別名時不保證召回；LLM關閉時的人工同義詞家族目前仍可能形成多個必要核心詞，須另設計精準同義詞 family group 接口與負例測試。
- **Merge warning:** 目前 `#400/#401/#402` 同時修改 active `.codex`；本工作依 `AGENTS.md` 先以 immutable SHA 驗證後保存五檔全文到 `.codex/archive/*-20261112-103600.md`，並濃縮 active 文件。合併前須保留所有 PR 的仍有效 API 合約/架構決策與 open issues，不可覆蓋他分支；使用者要求先看結果確認，不預先 merge。


## 2026-11-12 #397 P1-b bounded rescuer (candidate)

- Unmerged opt-in `SRAF_EVIDENCE_RESCUE=1` bounded parser-citation pool supports low-count strict (1–2) date-safe same-document weak rescue with hard caps and deterministic scoring. Python3.10/3.11 CI and independent latest-HEAD Codex review required. Keep off until actual operator evidence acceptance.
- **Next P1-c/d:** cover ES `inner_hits.size=3` source Evidence omissions without unbounded memory/re-fetch; global per-request budget/dedup and coverage/token-aware high-volume selection; integrate opt-in #401/#402 Evidence Trace for per-stage counts and reason codes; real `news_test` 5→1 incident diagnosis, recall/precision/latency p50/p95 still needed. Rebase/reconcile active `.codex` with open PRs and preserve #403 name-axis decision.

## 2026-11-12 — #397 P1-c source Evidence refill (first bounded slice)

- Candidate PR: default-OFF `SRAF_EVIDENCE_SOURCE_REFILL=1` **requires** `SRAF_EVIDENCE_RESCUE=1`; bounded source-only reparse for structured Evidence omitted by ES `inner_hits.size=3`, same strict-anchored original ordinal, canonical Event/Timeline date guard, strong-first/weak-marked candidate fill up to combined 3. Python3.10/3.11, date/refill/topic regression and independent exact-head formal Review are mandatory.
- **Further P1-c:** real Guterres 2023-08-24 5→1 root-cause analysis with per-segment reasons (see #401/#402 Evidence Trace); never infer 5 candidates were all present in `_source`. When enabled, consider query-level/phase-level global budgets, source diversity, evidence re-ranking, explicit count of uninspected source rows and safe operator comparison.
- **P1-d:** token-budget/coverage-aware high-volume top-k, deterministic signal and full report LLM validation still unresolved. No private `news_test`, p50/p95, Report Job, generated DOCX or airgap rollout was run. Integrate open #401/#402 active memory and builder changes before merging.

## 2026-11-12 — #397 P1-a trace integration (#401)
- Candidate PR #401 rebased through an explicit two-parent main integration, preserving #403/#404/#405 and restoring reviewed count-only retrieval trace. Added counters for selected #404 weak candidates and #405 bounded source strict/weak candidate/selection; keep `SRAF_EVIDENCE_TRACE=1` separate from both refill flags. Verify parser cap, Event/Timeline date failures, 5→1 case, privacy, 500+ items, and exact default-OFF equality with dual-version Hosted CI and independent exact-head Review before merge.
- **Still open:** #402 report-stage actual Evidence/LLM-input count-only trace and removal of raw per-citation log; true private `news_test` operator case, per-request cross-stage ID/union counts, p50/p95, token budget, source diversity, and true report correctness remain NOT TESTED. Review and integrate #402 from current main without overwriting either trace or existing Excel/Product/Report API contracts.

## 2026-11-12 — #397 P1-a Report Evidence Trace (#402 current-main integration)
- #401 retrieval Trace **MERGED** at `87a58cd2557e5826b2ef00d122fe97b9407709d9` with 7/7 Hosted CI and exact-head review clean. #402 is next: count-only actual pre-report-LLM Evidence pick/compression/pack, remove existing unconditional raw Evidence note/title/date/ID stdout, and test single shared opt-in flag on latest main. This candidate must pass new Python 3.10/3.11 CI and independent latest-head review before merge.
- **Future:** per-request safe correlation between ES candidate builder iterations and report LLM input, per-snippet deterministic removal reason codes, global candidate/byte/token budgets, high-volume source diversity and live `news_test` 2023-08-24 Guterres 5→1 diagnosis. Report chars not token counts; private LLM/DOCX and existing logger secrecy need separate scrutiny. #400 editor substring Mapping/performance acceptance and #396 LAN TLS IP SAN warning are separate blocked PRs.


## 2026-11-15 #397 P1-d — source-diverse report Evidence candidate (NOT MERGED)
- Candidate source diversity only: exact-head Python3.10/3.11 Hosted regression and formal Codex Review required before considering merge. Remaining #397 P1-d: whole-prompt model-specific token budget, time/topic/quality-aware ranking, cross-stage per-snippet reasons, 5→1 real `news_test` diagnosis, p50/p95 and report/DOCX accuracy acceptance. Do not conflate input bytes/chars with tokens.


## 2026-11-15 #397 P1-a — identified source coverage counters (NOT MERGED)
- Candidate identified-source counters aid coverage comparison of opt-in #407 selector. Remaining: per-snippet reason correlation, unknown-ID source coverage, Event/Timeline-specific attribution, true token budgets, p50/p95 and real Guterres 5→1 replay on private ES. Exact latest-head CI/Codex and confidentiality gate required.


## 2026-11-15 #397 P1-e — offline source-coverage comparison candidate (NOT MERGED)
- Operator may compare count-only baseline vs opt-in diverse selector using a reviewed CLI, but must verify same question/ES index/date/corpus externally and run actual private Guterres 5→1 recall + report/LLM/DOCX p50/p95, precision and true tokens. Candidate compare utility does not satisfy those acceptance gates; exact-head Hosted CI/Codex required.


## 2026-11-15 #397 — Report Evidence count-only Word/OpenWebUI visibility (CANDIDATE, NOT MERGED)
- P1 NEXT, separate from count-display PR: eliminate **unconditional single-document Evidence truncation** in ES nested (`inner_hits.size=3`) and parser source (`citations_per_doc=20`) for large server-structured records when safe request/global budget remains. Design bounded retrieval/pagination per query/time/field, global Evidence+byte/timeout/token caps, accepted/uninspected reason counters and cancellation; test 1 document 500 items with global remainder plus 2 docs and Event/Timeline guard. Private `news_test`, output precision/recall and LLM/DOCX acceptance must be independently verified.


## 2026-11-15 #397 — Experimental request-shared structured Evidence candidate budget (CANDIDATE)
- Follow-up shared budget: per-request matched-valid (post date/topic) cap rather than raw-citation-first, fair later-source allocation/round-robin, budget-exhaustion reason trace, bytes/token-aware final prompt and 500+/multi-index private ES p50/p95/precision/recall tests. Do not claim this opt-in 1024-candidate slice solves all 500/day server records or hidden ES retrieval pagination limits.


## 2026-11-15 — #397 P1-d / postfilter Evidence fairness (CANDIDATE, NOT MERGED)
- Created separate double opt-in `SRAF_EVIDENCE_SHARED_SOURCE_BUDGET=1` AND `SRAF_EVIDENCE_VALID_FAIR_BUDGET=1`, leaving main/#411 shared-source mode and default OFF untouched. Pre-source parser quotas water-filled by original ES hit ordinal within 2048 scanned/parsed citations and 1MiB shared source text; a deterministic strong-first round robin limits only date/topic-validated Evidence to 1024. Fixed count-only trace records eligible/selected/not_selected. No ES re-query/LLM/SQL/auth changes. 
- Synthetic 500+12 structured records, 980 wrong-date then 120 valid, invalid topic, later valid doc rescue, same UUID across indices, long text budget, and trace privacy tests. Hosted Python3.10/3.11 exact-head CI, formal Codex Review and real private ES/LLM/DOCX/performance acceptance are PENDING. Candidate quotas can still scan a bounded prefix and cannot prove exhaustive recall, perfect fairness or token budgets.

## 2026-11-15 #413 — adaptive retrieval agent follow-up (A0 diagnostics only)
- A0 candidate reports per-builder count-only health but **must not** autonomously re-query from a slice: date-refill may call the builder repeatedly, ES may return only `inner_hits.size=3`, and unknown source rows are not proven date/topic valid.
- Next independently reviewed A1: request-wide aggregation and immutable original question/date/index/RBAC/field constraints, hard request deadline with generation reserve, ES/LLM/candidate/token/page count budget, no-drift facets and monotonic evidence checkpoints. Then B: conditional N-round query reformulation with real OpenWebUI-compatible progress/cancellation protocol. C: private live acceptance and two-flag retirement plan; do not enable `SRAF_EVIDENCE_SHARED_SOURCE_BUDGET`/`SRAF_EVIDENCE_VALID_FAIR_BUDGET` by default before acceptance.

## 2026-11-15 #413 next after #414 — retrieval health / OpenWebUI
- #414 merged as diagnostics only: no request-level quality aggregation, actual adaptive rounds, hard deadline, cancellation, progress transport or automatic #411/#412 flag retirement. Redact unsafe stdout in search tool before adding more repeated queries.
- Next request-level planner must preserve immutable date/index/field/permission bounds, monotonic validated Evidence checkpoints, hard ES/LLM/token/time budgets and generation reserve; requires actual OpenWebUI/proxy SSE or Job progress acceptance and real disconnect/cancellation tests. Do not enable experimental flags or claim FULL_LIVE before operator acceptance.

## 2026-11-15 #413 A1 follow-up — request-wide budgets (in progress)
- PR #414 and #415 have been verified merged; per-builder health and limited ES stdout redaction exist. Candidate optional date-refill admission adds an atomic ES page count + monotonic generation-reserve guard, not an automatic runtime budget. Next integration requires a single request-wide trusted coordinator across first ES, candidate refill, optional N rounds and Report LLM with timeouts, byte/token and call budgets, cancellation, non-drifting date/index/field/RBAC, checkpointed Evidence and verified OpenWebUI visible progress. Do not falsely interpret optional admission or synthetic PASS as completed multi-round agent.

## 2026-11-15 #413 B0 dual-agent contract follow-up (candidate, NOT MERGED)
- [ ] Hosted exact HEAD Python3.10/3.11 planner + existing date/keyword regressions, formal independent Codex review, thread cleanup and normal branch protection gate.
- [ ] Build truly **request-wide** validated Evidence checkpoint/coverage evaluator (current #414 is only one builder slice); freeze user-authored temporal/fixed field/index/owner constraints using a trusted original-text verifier, not freeform Data Agent JSON.
- [ ] Bind independent round-2..N planner to a trusted ES query adapter; keep initial core entities, optional SHOULD semantic terms, index/field/date restrictions, original Event/Timeline postfilter, monotonic cross-index/Event-block/time Evidence dedup, robust budget admission and explicit INCOMPLETE.
- [ ] Add genuine Job-mode N-round controller in existing ReportJobWorker, total retrieval 1800s + generation reserve, LLM/ES/token/round budgets, cooperative cancellation, restart-aware checkpoints; reuse first-round validated evidence only with owner/scope proof. #417 queued cancellation foundation is separate/open.
- [ ] Authorize and perform private news_test/LLM/DOCX, OpenWebUI two-link auth, data consistency/p95 and full privacy/timeout acceptance before production enablement/flag retirement.

## 2026-11-15 #413 Report Job async implementation follow-up (first foundation PR CANDIDATE)
- [ ] Exact-head Hosted Python 3.10/3.11 CI, formal independent Codex review and security-thread resolution for queue admission + queued-only cancel. Then merge only per Auto-Merge v2 gate.
- [ ] Add strictly validated durable adaptive_multiround mode, round checkpoints with validated canonical Event/Timeline date and source identity, immutable query/tenant/permissions; LLM plan/query drift guard; request-wide ES/LLM/token 1800s retrieval and ~2400s total budget with generation reserve, cooperative cancellation/timeouts and actual restart policy.
- [ ] Only AFTER real adaptive worker exists, add opt-in authorized Chat Completions post-single-round dispatch with stable per-turn idempotency, protected single-round Evidence checkpoint re-use and secure browser status/Word capability. Avoid treating shared OpenWebUI service key or unverified headers as distinct user identity. When no trusted user identity, leave auto dispatch disabled.
- [ ] Validate resource queue timeout/retention and per-owner fairness; no background GPU starvation for single-round chat. Test private Linux ES/LLM, real DOCX, browser-proxy links, disconnect, service restart and p95 before enabling defaults. OpenWebUI SSE P2.


## 2026-11-15 #413 B1 request-wide admission follow-up (PR CANDIDATE)
- [ ] Exact-head Python3.10/3.11 Hosted CI and formal Codex Review of the isolated atomic request budget; merge only with approvals/protection satisfied.
- [ ] Wire budget into a **trusted, Job-only** adaptive coordinator after canonical date/index/field/owner validation and real request-wide Evidence checkpoint; admit every ES/LLM call including initial search; add provider-level per-call timeouts and cooperative cancellation before claiming 1800s/2400s enforcement.
- [ ] Expand to token/bytes budgets, retry accounting, restart persistence and per-owner GPU fairness; independently validate private Linux/ES/LLM/Word, browser capability and OpenWebUI single-round-plus-deep-Job link flow. Do not enable automatic Chat dispatch or retire experimental Evidence flags on this helper alone.


## 2026-11-15 #413 B2 Report Job browser fragment prefill (PR CANDIDATE)
- [ ] Exact-head Hosted Report Job UI/Node and offline regression, independent formal Codex Review and Merge Gate.
- [ ] Before producing a deep-report link in `/v1/chat/completions`, implement explicit authorized Job dispatch with durable admission, owner-bound idempotency, correctly preserved original question/query constraints, real N-round execution and verified browser/proxy permissions. Do NOT include service keys or access tokens in query strings/fragments, or pretend a `#job=` link is a signed one-click capability.


## 2026-11-15 #413 B3 browser URL producer (PR CANDIDATE)
- [ ] Confirm exact-head Hosted Report Job UI/API regressions, independent Code Review and Merge Gate for additive `browser_status_url`.
- [ ] Wire to Chat only after trusted user/tenant-bound deep Report Job creation is accepted and actual N-round worker mode is implemented; return a stable status prefill and explicitly say `QUEUED/RUNNING` until Word exists. Check OpenWebUI/forward proxy original scheme/host configuration before constructing an absolute external URL. Never place service keys in URL.


## 2026-11-15 #406 — next after single-round 3→2 count-only shadow
- [ ] Run exact-head dual-Python CI and independent formal Codex review; conditional merge with clean findings and branch policy.
- [ ] Read-only private news_test same-snapshot A/B on 2025 Gaza (5/10 vs 25/40) and Event-only date examples. Determine where parser/inner_hits/strict group cutoffs actually happen and identify false positives.
- [ ] Implement trusted original-question entity/subject anchors and same-ES-hit/block-local matching; distinguish auxiliary groups and meta-only, do not cross-borrow events or UUID. Only then trial conditional 3→2 under bounded validated candidate/token/source budgets, without auto enabling flags.
- [ ] Standardize reusable single-round Evidence selection contract before #413 N-round execution PR. Existing #418/#419 are isolated planner/admission helpers, NOT a live deep report.


## 2026-11-15 #406 after parsed weak rescue same-Event guard
- [ ] Verify PR candidate latest-head Hosted dual-Python full Evidence regressions and formal Codex review, resolve any findings and conditionally merge.
- [ ] Apply the same source-hit/block/Event context rule to **weak candidates** created by `source_refill_candidates` (#405) in a separately serialized PR. Strict direct-text matches in any valid Event should remain independently allowable when verified; never lend anchor to unrelated weak E2.
- [ ] Obtain trusted required original-question entity anchors before enabling any automatic two-group relaxation; compare actual private news_test 5/10 vs 25/40 A/B and invalid cross-topic sources. Old and new rescue remain default-OFF pending operator acceptance.


## 2026-11-15 #406 after E1/E2 source-only weak rescue hardening
- [ ] Exact-head Hosted Python3.10/3.11 and independent Codex review of source refill guard, then conditional merge; no parallel core-edit PR.
- [ ] Build trusted original-user subject anchors to distinguish Gaza from unrelated Sudan even in *strict* or zero-only fallback; use same-block/local Event checks and bounded candidate rescue. Run private news_test same-snapshot precision/recall, Event-only date and p50/p95 A/B before enabling #404/#405, retiring #411/#412 flags, or wiring #413 real multi-round engine.


## 2026-11-15 #406 next after original-question provenance context
- [ ] Verify dual-Python exact-HEAD Hosted tests and Codex review, no unresolved Findings, conditional Merge.
- [ ] Extract high-confidence subject anchors strictly from verified original report question (not LLM query or broad synonym group); distinguish required entity vs auxiliary facet and negative/comparison constraints, allow no-anchor result. Keep outputs trace-only/shadow for safety and privacy.
- [ ] Connect subject anchor diagnostics to bounded 3→2 shadow via the same internal single-round builder; check Event/block/owner scope, private news_test A/B precision-recall and p95 before any automatic two-group Evidence promotion or default flag retirement. Do not connect live #413 N-round worker ahead of this.


## 2026-11-15 #406 after explicit original-question subject candidate
- [ ] Exact HEAD Python3.10/3.11 Hosted CI and Codex Review; merge only after gates.
- [ ] Connect the explicit candidate to bounded `topic_shadow.py` via original report ContextVar, count only date-qualified, same-event text-anchored 3→2 candidates without exposing original terms. Do not activate automatic promotion before operator news_test A/B.
- [ ] Later expand to true general user-intent entity/required-subject detection with independently validated trustworthy equivalence aliases, negation and multi-entity constraints; invalid/uncertain must fail closed. Confirm source-level subject/UUID doesn't authorize another Event or source, and preserve legacy output.


## 2026-11-15 #406 next after worker-thread original question safety
- [ ] Exact-HEAD dual-Python Hosted, independent Codex Review and merged branch gate; inspect Requirement E2E tool scope regressions and scope reset across thread exceptions.
- [ ] Wire original question via Tool.forward to internal bounded per-builder `topic_shadow`, using #426 explicit candidate only under Trace, and same Event/block linking for indirect document context. Don't expose subject in count-only logs or enable automatic promotion. Verify real private smolagents/report runner can deliver context across its actual thread model.
- [ ] Private news_test snapshot A/B Gaza/UN/Sudan precision-recall, count trace, Event-only date plus report token budget before considering new default rules or #413 N-round runtime wiring.


## 2026-11-15 #406 after explicit-subject 3→2 shadow hookup
- [ ] Complete exact-head Python 3.10/3.11 Hosted CI and independent Codex Review, fix any findings, conditionally merge (no parallel source/builder PR).
- [ ] Extend count-only shadow with conservative same ES hit + block-local + overlapping Event IDs borrowing from validated date-matched **direct subject text** Evidence; do not let global document title, cross-event, cross-UUID or unrelated source establish a required subject. Keep absent/ambiguous original fail closed.
- [ ] Genuine human-assessed private news_test read-only same-snapshot Gaza 2025 5/10 vs 25/40, Sudan false positives, Event-only/date-null and Guterres 2023 cases; profile p50/p95 and token budget. Implement robust original-question entity requirements in ordinary prose separately before any automatic nonzero strict 3→2 promotion and #413 multiround worker.


## 2026-11-15 #406 after Event-local contextual 3→2 shadow
- [ ] Latest-HEAD Hosted dual-Python, formal Codex review and conditional merge (never parallel-modify Evidence Builder/Trace).
- [ ] Distinguish two fully TEXT-matched auxiliary axes from text+metadata-assisted two-group candidates in contextual shadow (avoid treating title/metadata as proof). Add mismatch/negative/comparison and optional typed semantic quality gates before any promotion; actual normal user questions need trustworthy entity extraction rather than only `主題：...` label.
- [ ] Run real private read-only `news_test` same-snapshot Gaza/Sudan 5/10 vs 25/40, Guterres Event-only 2023-08-24 and missing Timeline; compare p50/p95 and source fairness, eventual report tokenizer-based input budget. Implement conditional 3→2 only after documented precision/recall target and operator acceptance, then share core with actual #413 N-round Job Worker.


## 2026-11-16 #406 next after two-text-axis shadow metrics
- [ ] Latest HEAD Hosted CI Python3.10/3.11 and independent Codex Review with zero unresolved findings; conditional merge only.
- [ ] Preserve exact provenance: do NOT promote mixed one-text + one-metadata candidates merely because same Event matches; compare two-text-axis hypothetical candidates against the original question's validated required entities and issue constraints and block cross-Event source subject borrowing.
- [ ] Finish true original question named-entity/negation/conjunction semantics for naturally phrased questions (not only `主題：...`), private read-only news_test Gaza/Sudan 5/10 versus 25/40 and Guterres Event-only A/B with precision/recall, p50/p95 and token-size/cost budget, then decide gating for conditional 3→2 and N-round reuse.

## 2026-11-17 — N-round owner-bound execution wiring (candidate)
- [ ] Verify latest-head Python3.10/3.11 Hosted CI, formal Codex findings/threads and merged status of the isolated leased executor; no private Linux required for code review. Never mark as merged based only on this note.
- [ ] Later: trusted mode/admission binding inside existing ReportJobWorker, genuine tenant per-index RBAC and all-question branch policy, end-to-end 1800s retrieval + generation reserve and cancellation, real ES/semantic LLM/Word L3-A. Formal independent Job/Artifact CAS and user-facing OpenWebUI second-job status/link remain separate gates. Keep N rounds and Word authority OFF.
