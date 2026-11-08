# SRAF Backlog — Active, 2026-11-08

## Current Focus: Zero-memory Linux operator discoverability + private host evidence

- **2026-11-08 candidate (CI/Review PENDING):** add executable root `0_一鍵快檢_SRAF.sh`, named to sort at the top of checkout; no args runs exactly existing `deploy-check`, `--help` displays Chinese offline safety/readout guidance; all other arguments rejected. Add top README link, root operator docs, release policy selection and subprocess tests. It is intentionally not a desktop auto-trusted launcher, not a changed default quick behavior and not a new probe.
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
