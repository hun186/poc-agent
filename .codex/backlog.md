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

- **2026-11-11 #397 P1-a retrieval-stage diagnostic PR #401 OPEN (candidate, not merged):** Fixed-schema opt-in `SRAF_EVIDENCE_TRACE=1` (default OFF) logs bounded per-builder source/inner/citation counts, parser cap, date rejection, strict/relaxed/fallback topic reasons and selected result counts; no text/query/source IDs, dates, event IDs, prompts or extra ES/LLM. Synthetic Python 3.10/3.11 CI and existing temporal/date-refill regressions are staged; **latest-head Hosted / formal Codex / private index evidence acceptance must be verified separately**. Real 2023-08-24 Guterres five→one sample still NOT TESTED. Feature does not solve/claim #397 P1-b candidate retention, P1-c date-safe low-evidence refill, P1-d coverage/token budget or later report dedup / actual LLM prompt evidence trace.
- **2026-11-11 #397 pending next-stage design:** Add correlation across ES `date_candidate_refill` builder passes without counting the same citation twice; instrument `agent/report_agent.py` strong/weak 120-limit → `compress_evidence` dedup → `pack_ev_for_llm` → actual LLM submission using privacy-safe request-scoped counters. Preserve incomplete-search fail-closed logic, report citation dates, no additional LLM, and no raw prompt/UUID in new trace. Review preexisting content-bearing ES/report debug `print` separately before exporting logs. Enforce bounded storage/logging and performance acceptance on live private ES.
- **2026-11-11 concurrent PR coordination:** #400 Editor .codex compaction is open and may conflict with #401's independent required archive/compaction; resolve current main vs each PR's active memory at merge time. Do not drop archives, overwrite merged project memory, or merge #396 SAN security exception as collateral.
