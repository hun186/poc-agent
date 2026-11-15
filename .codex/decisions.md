# Architecture and Engineering Decisions — SRAF (compacted 2026-11-12)

## Current Summary
### Core authority and trust

- Keep existing `sra_api/` and `api/` compatibility, real Agent/LLM/ES/DOCX, Auth/RBAC/owner isolation and audit. Do not create replacement auth, scheduler, Report Job queue or mocked production authority.
- SQL Server Requirement Set/Version/Snapshot is authoritative; `sra_schedule` versions, Handoff leases and fencing own recurring execution; API-lifespan Report Job Worker owns reporting. SQL transactions do **not** atomically encompass external HTTP, Elasticsearch or filesystem writes.
- Product v4 Tasks require superuser provisioning/activation and owner/CAS-revision fencing. Service keys only use permitted provisioned operations; idempotency binds principal, route/target and canonical semantic payload (including empty-body Run). Draft changes require independent authorization.
- Deployment provenance must have independently reviewed source/manifest policy identity, exactly hashed managed release inputs and strict active module/path checks. Deployment-local SQL registry/credentials are never included, printed or automatically uploaded. `release` fails closed on drift; `functional` tolerates only specifically allowed ordinary runtime-byte drift and **cannot** establish release acceptance.
- OFF-0/1/2/3 and Hosted tests are `PARTIAL_ONLY_NOT_ACCEPTANCE`. Strict TLS CA+IP SAN required before any authenticated private ES/SQL request; SAN WARN and no-network/anonymous TCP are not release trust.
- Operator E2E preflight occurs **only** on authorized operator request, never ordinary API startup (#319). The server's 540s cooperative limit and Linux client's bounded 600s GET timer are not SDK/ES cancellation. On timer conflict or untrusted API socket, fail closed before credentials.
- Dedicated ES E2E fixture uses exact owned index/IDs/full source and create-only missing-doc recovery, no auto-delete/rollback. Operator E2E capability Plan is process-local and immutable, published only after whole successful preflight; rerun suspends new admission on failure/drift; in-flight verified jobs keep pinned Plan including their tool threads. Production reports always use real LLM/ES.
- Linux same-UID/project private flock and opaque epoch can revoke stale local plan admissions; this is neither distributed lock nor peer Worker Plan authorization. Future distributed guarantees require separate design and approval.
- Preserve staged real Report Job progress in existing SQLite v2 and existing owner-scoped status/download API; no invented percentage, GPU attribution, hidden timeout or new queue. Browser keeps bearer in memory, same-origin HTTPS and no blind POST retry.

### Operator and release design

- Reuse canonical OFF-1 probes via a conservative root shell dispatcher. `quick` is anonymous and read-only; `diagnose` can opt into bounded TCP; `no-network` never opens sockets; authenticated ES/ODBC tests and Report Job execution remain separately selected. OFF-1S listener proof is mandatory before bearer and is not equivalent to passive process observation.
- SQL OFF-1G executes only a fixed least-privilege ODBC18 TLS-authenticated `SELECT CAST(1 AS int)`, not SRAF production SQL registry operations. ES OFF-1B checks strict TLS/IP SAN and bounded literal configured index reads; do not weaken identity requirements or test invalid credentials in routine quick checks.
- Evidence output remains under an existing checked private no-follow dirfd tree; optional absolute operator-selected path is subject to the same rules. OFF-4 diagnostic TXT uses fixed allowlisted cause/remediation tuples; no raw error, prompt, model, SQLSTATE, host path or secrets.
- OFF-2 release selection uses nine **explicit** existing operator root Shell/Python paths, not blanket trust of `tools/`. List-only hash checks require a separately trusted SHA-256 of the manifest and are always partial; no implicit pin calculation, wheelhouse, OS/ODBC/model transitive dependency claim, generated signatures or migration. OFF-5 real restore remains separate.
- **Issue #354 canonical real E2E input:** use null `DeadlineDT` (existing `empty_to_null` optional `expires_at`) rather than arbitrary far-future date or runtime mutation. Preserve all three real ITEMNO/TITLE/CONTENT and non-expiration cells; keep historical workbook unchanged for exact data comparison. New canonical SHA `fa5171dce02630ace09b042be3b490995bdedf0152bf9b61af30ba1fe682843d` is a source-file pin **not** an attested/signatured release manifest. A reviewed build and private Linux `FULL_LIVE` remain mandatory.

## Recent Decisions
- **2026-11-12 synonym alias precision:** Limit equivalence-class union to explicit LLM synonym links between actual input *core terms*; use earliest input representative, do not union on mere substring matching or noncore overlap. Remove shared ambiguous noncore aliases instead of letting them satisfy unrelated required axes. Expand traditional/simplified variants after stable grouping; keep the same single synonym LLM call and date-safe Evidence contract. Prompt checks official↔common names only for confirmed identical referents and forbids nearby/related entities. Synthetic-only verification; no implicit live ES accuracy guarantee.
- **2026-11-12 merge gate:** user requested reviewable before/after; hold merge until their confirmation, independent final-head CI/Review and `.codex` reconciliation with other open PRs. No production deployment or credentialed tests.

## Archived History
- Full pre-compaction decisions: `.codex/archive/decisions.md-20261112-103600.md`, verified source SHA `723b3602d143d5df5d15f773d23e43dbdebb6db2`.


- **2026-11-12 #397 P1-b design (not merged):** To avoid unsafe broadening, default `SRAF_EVIDENCE_RESCUE` OFF. Opt-in eligible only when 1-2 strict citations exist, ≥2 topic groups, strong strict Evidence-text anchor in same ES source-hit ordinal, canonical Event/Timeline date validator passes and candidate has a topic **text** match. Mark rescued citations weak, deterministically prefer topic-group count and ES relevance; skip oversized text, cap candidates/characters/inspected citations/documents. No model/ES calls, no cross-doc UUID correlation, no relaxation of zero-count existing fallback. Leave global adaptive P1-c and token-budget P1-d separate.

- **2026-11-12 #397 P1-c conservative design (candidate):** the source-only stage requires the prior #404 flag and new independent `SRAF_EVIDENCE_SOURCE_REFILL` opt-in. Restrict to strict Evidence-text anchored ordinal; inspect only existing ES response `_source` with hard per-doc/event/JSON/text caps, and reparse an allowlisted source-only structured projection rather than creating a second date linker. Require complete local Event/Timeline links, canonical date validation, at least one literal text topic-axis match, no metadata-only rescue. Keep original strict before new source strict and weak, never cross-doc UUID match, no LLM/ES/SQL calls, default results unchanged, and no auto-deploy without operator acceptance.

- **2026-11-12 #401 merge strategy:** preserve full current main (merged #403–#405) and old #401 history with a two-parent integration commit, then reapply reviewed trace-only parser/snippet modules and explicitly integrate count-only instrumentation around both #404/#405 rescue branches. Never replay stale `.codex` snapshots or roll back source date guards. Trace stage key allowlist and bounded integer values protect privacy; record only candidates/selected counts with no raw text, identities, dates, Event IDs, or source paths. No new API/LLM/ES calls. Final exact-head CI and independent Codex Review are merge prerequisites.

- **2026-11-12 #402 integration decision:** preserve all current #401 retrieval trace, #403 alias grouping, #404/#405 bounded date-safe Evidence rescues and still-valid Product/Excel/Report API contracts. Reapply previously reviewed #402 count-only report boundary with its existing `SRAF_EVIDENCE_TRACE=1` opt-in, remove unconditional raw Evidence preview logging rather than moving secrets behind a flag, and keep a separate schema from retrieval. Do not invent cross-stage correlation or token accuracy; validate new exact-head Python3.10/3.11 Hosted CI and independent formal Codex Review before merge.


## 2026-11-15 #397 P1-d — source-diverse report Evidence candidate (NOT MERGED)
- Preserve default strict-first report Evidence selection; alternative is explicit opt-in `SRAF_REPORT_DIVERSE_EVIDENCE=1`, round-robin among prevalidated source IDs within strong/weak classes. Unknown IDs are separate groups; no data mutation/ES fetch/LLM call. Deterministic count coverage is preferable to silently promising semantic ranking or a token limit. Keep feature off for live use until separately approved evidence.


## 2026-11-15 #397 P1-a — identified source coverage counters (NOT MERGED)
- Reuse existing opt-in `SRAF_EVIDENCE_TRACE=1` and emit numeric identified-source coverage for incoming/picked/actual LLM-input rows; no independent second trace channel or ID hashes. Reconcile post-field-selector rows by existing `ref_no` instead of requiring the LLM to receive UUIDs. Keep additive v1 count-only log schema, no HTTP/API response change.


## 2026-11-15 #397 P1-e — offline source-coverage comparison candidate (NOT MERGED)
- Prefer one opt-in offline stdlib compare CLI over collecting private report/ES content or adding live API probes. Strict read-only bounded regular input, one record per file, numeric allowlist output, generic INCOMPLETE error with no local paths/raw payload. Comparison success is `PASS_PARTIAL`, never full report or token acceptance.


## 2026-11-15 #397 — Report Evidence count-only Word/OpenWebUI visibility (CANDIDATE, NOT MERGED)
- Use shared strict numeric-only Evidence usage contract and one common display formatter for Word/OpenWebUI; no direct ingestion of arbitrary logs into DOCX or browser, and no IDs/prompts in added count metrics. Preserve existing `SRAF_EVIDENCE_TRACE` logger and default-OFF source-diverse choice independently. Explicitly distinguish known-source retention from topic coverage and whole-corpus completeness.


## 2026-11-15 #397 — Experimental request-shared structured Evidence candidate budget (CANDIDATE)
- Never remove parser limits wholesale. Opt-in source preference only for documents with structured Event/Timeline, with a shared 1024 candidate and separate 2048 source-row/1MiB text ceilings; no additional ES round trip or automatic live enablement. Retain Event IDs & block-local date guard before Evidence survives, and leave unstructured/default-off path stable. Production activation requires operator acceptance/reversal.

- **Codex #411 P2 fix at new HEAD (recheck pending):** preserve inner-hit citations by deduplicated, bounded union with source citations even if 1MiB source scan cuts off before a date-valid tail match; restore exact default-OFF parsed-before-selected trace count semantics; preserve numeric string paragraph/source IDs after JSON normalization. Added partial-source and numeric-ID regressions. Latest-head full Hosted CI/formal independent Codex re-review remain required before merge.

- **2026-11-15 PR #411 latest Codex P2 array-text follow-up:** preserve existing one-element list-valued `text` (e.g. `['內容']`) under opt-in shared-source scan by bounding the one-item container then validating the inner string against original 4096-char and 1MiB request ceilings; reject nested/multi-valued arrays. Regression covers default OFF vs ON, four date-valid rows and oversized input rejection. Exact-head Python3.10/3.11 CI and fresh formal Codex Review still required; no private ES/LLM/DOCX claim.

- **2026-11-15 PR #411 Codex P3 Trace fix (pending latest-head re-review):** add fixed `inner+source` parser-mode enum to `EvidenceTrace.parsed_hit` allowlist (previously silently downgraded to `none`). Add default-OFF `inner` versus opt-in `inner+source` diagnostic count/absence-of-private-text regression to existing Python3.10/3.11 Evidence Trace workflow. Still no private ES/report/latency acceptance.


## 2026-11-15 — #397 P1-d / postfilter Evidence fairness (CANDIDATE, NOT MERGED)
- Created separate double opt-in `SRAF_EVIDENCE_SHARED_SOURCE_BUDGET=1` AND `SRAF_EVIDENCE_VALID_FAIR_BUDGET=1`, leaving main/#411 shared-source mode and default OFF untouched. Pre-source parser quotas water-filled by original ES hit ordinal within 2048 scanned/parsed citations and 1MiB shared source text; a deterministic strong-first round robin limits only date/topic-validated Evidence to 1024. Fixed count-only trace records eligible/selected/not_selected. No ES re-query/LLM/SQL/auth changes. 
- Synthetic 500+12 structured records, 980 wrong-date then 120 valid, invalid topic, later valid doc rescue, same UUID across indices, long text budget, and trace privacy tests. Hosted Python3.10/3.11 exact-head CI, formal Codex Review and real private ES/LLM/DOCX/performance acceptance are PENDING. Candidate quotas can still scan a bounded prefix and cannot prove exhaustive recall, perfect fairness or token budgets.

- **Follow-up before formal review:** source text quota now reserves an up-to-4096-char minimum per active ES source when total shared 1MiB can support it, so a single later long valid record is not starved by an early 2000-row source; strict global budget remains. Demand planner also counts returned direct named `evi` inner hits when `_source` snippets are absent, maintaining 3 verified inner hits in that scenario. Added dual-Python synthetic regression, still no live acceptance.

- **2026-11-15 extra fairness regression:** parser transfers only *unused actual* source-character budget from earlier ES hits to later hits; retains every later hit's reserved text share plus global 1,048,576-character ceiling. Prevents a legitimate 3996-character last hit from being dropped after 300 short prior documents despite unused budget. Python3.10/3.11 exact-HEAD CI and fresh independent Review mandatory.

## 2026-11-15 #413 — partial Evidence is preferable to silent timeout (CANDIDATE)
- Add an optional trusted-internal next-ES-page admission hook before enabling adaptive rounds, with a monotonic deadline and reserved generation time, no user-facing algorithm feature flag. If denied, retain only canonical date/topic-validated Evidence and explicitly mark search incomplete; never silently return no relevant articles or fabricate unexamined citations. In-flight ES/network cancellation and end-to-end OpenWebUI/proxy deadline are separate obligations and require independent validation.

## 2026-11-15 #413 B0 — user-approved two-agent strategy (CANDIDATE)
- Keep original first-round keyword extraction/prompt. Build a **separate round-2..N AdaptiveRetrievalPlanner** using prior search history, verified Evidence coverage gaps and cumulative budget to propose new optional semantic search axes. Both agents must reuse the same canonical ES, Event/Timeline date verifier, Evidence filtering and report modules; no second retrieval stack.
- Hard date/analysis periods, index, fields, core entities and manual-only keywords remain frozen in trusted server-owned QueryConstraints. Search result shortage never relaxes date. If original date parsing is demonstrably wrong, planner may only request trusted automated reparse (no human approval); revalidated versioned scope/checkpoint is later work, never direct LLM date mutation.
- No production integration before #397 single-round verified health, query-plan adapter, long Job budget/cancel and private acceptance.

## 2026-11-15 #413 long-report execution decision (PR CANDIDATE)
- Build future adaptive N-round retrieval inside the existing Report Job Worker/Agent; do not keep a Chat Completions HTTP connection open for 30m retrieval+10m generation. Preserve standard single-round Chat response, optionally submit a durable deep Job after single-round results only when verified user/tenant ownership, idempotency and resource admission are established; return a status link, not a promised completed DOCX.
- First narrow foundation: optional transactional bounded queue admission and queued-only cancellation, default preserving existing HTTP behavior. No unreviewed mode flag enables a fake adaptive job. Browser capability links, per-round canonical verified Evidence checkpoints, request-wide budget/stop and final OpenWebUI opt-in remain separate gates.


## 2026-11-15 #406 conservative question-subject semantics
- Distinguish request-local *original question* (#425) from LLM-refined/Data Agent core search terms. For first-stage offline subject-anchor policy use one explicit first-line user-written subject marker and exact unique semantic-axis membership; no generic NER heuristics or LLM-generated aliases are allowed to become mandatory without independent verification. This introduces a fail-closed optional candidate for subsequent shadow diagnostics only; it does not infer that ordinary unlabeled questions have no needed topic, nor does it authorize 3→2 Evidence admission. Real original-question disambiguation and precision/recall validation are separate gated work.
