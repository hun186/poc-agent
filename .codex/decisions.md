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
