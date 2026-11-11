# Project Memory — SRAF (active, compacted 2026-11-11)

## Current Summary

- **Source of truth:** Current GitHub main, exact PR HEAD, Hosted CI, formal Codex Review receipts, tests and `AGENTS.md` supersede historical planning/pending notes. GitHub PR merge != private Linux deployment or production acceptance. Never infer a real LLM/ES/SQL/DOCX PASS from synthetic tests.
- **Production system:** FastAPI Agent/LLM, Elasticsearch, SQL Server immutable Requirement Set/Version/Snapshot and versions, separate Schedule/Handoff workers, existing owner-scoped SQLite Report Job/DOCX/RBAC/audit. Do not add alternate queue, weaken ownership/authorization or silently change Product/Report contracts.
- **Release/operations:** OFF-0/1/2/3, offline L0/L1 and local `PASS_PARTIAL` are strictly partial; OFF-1S exclusive socket identity precedes privileged Bearer; strict CA/IP SAN is the trusted production TLS baseline. L2 SQL/ES/model and L3 real Report Job/Requirement/Agent/DOCX are separate operator opt-ins. Cooperative timeout is not SDK cancellation. Signed complete Wheelhouse/native ODBC, physical airgap and restore remain NOT TESTED.
- **Deployment:** Actual private Linux is a one-way incremental **Windows Robocopy/7z overlay**, not a Git checkout. Never instruct Git fetch/worktree/pull on Linux; deleted GitHub files can persist on host. Do not write private credentials, raw Evidence, queries, prompts or host paths to shared logs/archives.
- **Temporal Evidence:** #395 merged to main 2026-11-11, #394 closed without merge; Event/Timeline source-block-local event IDs/precision and bounded ES candidate refill produce report completeness warnings. Real private `news_test` date, Mapping, paging and DOCX acceptance remain NOT TESTED.

## Recent Changes / Current Branch Work

- **#400 OPEN (independent):** Editor mapping-aware substring/nested search candidate HEAD `127c4c082b7d075cf06b0f3e6aa5e9111a1cbf90`; previously verified latest-head Hosted 6/6 SUCCESS and completed formal Codex clean, all six review threads resolved. Private ES large-index substring latency and expensive-query policy not accepted; do not auto-merge based only on synthetic success.
- **#396 OPEN (independent):** Operator-only CA-verified IP SAN mismatch warning candidate HEAD `5cab77ebb4c9f3a20643fe53cee05923112014bd`; general Review/CI clean, independent security assessment and high-risk approval not established. Do not conflate SAN WARN with authenticated peer identity or FULL_LIVE release acceptance.
- **#401 OPEN / current task (2026-11-11, #397 P1-a first slice):** `SRAF_EVIDENCE_TRACE=1` opt-in retrieval-stage observations in `agent/es/evidence_core/{trace,parser,snippet,builder}.py`. It records bounded counts and fixed reason codes for ES source candidates vs returned inner hits, parser cap, source selection, date rejection, strict/relaxed topic rejection, fallback and selected Evidence. Random trace id and numeric per-builder ordinals only; default output and report pipeline unchanged. Codex P2 found that a source-loop 25→20 cap previously hid five never-examined raw rows; fixed with `parser.source_uninspected_after_cap` (validity unknown), plus synthetic regression. Latest post-fix HEAD CI/review still required. Trace does not log raw query/source content/identifiers or date, and does not correlate separate ES refill evaluations. New Python 3.10/3.11 Hosted regressions and runbook. **Latest HEAD CI, formal review, Merge Gate and private Guterres 2023-08-24 5→1 observation are separate pending gates** until verified. Final LLM input counts and report truncation are not traced by this first slice.
- **Recent operator L1 (historical, not FULL_LIVE):** Linux API healthz 200, Workers sometimes 2/2 identity, SQL/ES/LLM TCP reachable, but native ODBC, strict ES Mapping/TLS, real LLM, E2E/DOCX and signed release not established. Root `0_` shortcut removed from GitHub may remain on host; canonical `1_完整診斷驗收_SRAF.sh` requires operator validation before obsolete-file cleanup.
- **Previous verified merges (2026-11-08):** #368/#369 optional-import safe passive identity, #371 quick offline checker and #373 diagnostics launcher relocation all Hosted-tested/merged; no actual private FULL_LIVE proof.

## Open Handoffs

1. **#401:** await exact latest PR HEAD Python3.10/3.11 Hosted suite + formal Codex Review, resolve findings before any Merge Gate. Log privacy audit and real index date/inner_hits checks remain NOT TESTED; only retrieval stage instrumented.
2. **#397 P1-b/c/d:** bounded candidate conservation, low-evidence deterministic date-safe refill, diversity and hard LLM token budgets, downstream report dedup/selection/prompt counts with provenance; no additional LLM by default. Never revive date-invalid or cross-block mislinked Evidence.
3. **#400/#396:** leave separate mapping performance and TLS security gates; avoid conflicting PR merge without reconciliation, including concurrent edits to `.codex/*.md`.
4. **#393/#290:** real Event/Timeline ES samples, platform native/ODBC/SQL, Worker/Handoff, model and DOCX, trusted packaging/airgap/install/rollback remain independent operator acceptance.

## Archived History

Full original active files were **archived before compaction and independently re-fetched to identical blob SHA**:
- `.codex/archive/memory.md-20261111-204500.md` — `6441409ff5b433d4362c8af5de0b856f2775ff02`.
- `.codex/archive/known_issues.md-20261111-204500.md` — `3a5dec9e56b9999c45c5873d7f593b630f4a6358`.
- `.codex/archive/decisions.md-20261111-204500.md` — `723b3602d143d5df5d15f773d23e43dbdebb6db2`.
- `.codex/archive/architecture.md-20261111-204500.md` — `f4637f782b33c39c410eff822fd1bc6a44d6c80b`.
- `.codex/archive/api_contract.md-20261111-204500.md` — `3ca0b353bac76615fa2aaa336b7c5d2e0ab3c313`.
Earlier archives remain intact; these historical records do not attest current PR acceptance.
