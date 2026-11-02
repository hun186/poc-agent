# Architecture and Engineering Decisions

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

- Operator DataAgent and shared LLM paths report only redacted stage/outcome/classified exception and monotonic elapsed; no retries, shared queue or fake E2E model scope for ordinary reports.
- Use owner-scoped authentic Job phase and Word checks instead of frontend simulated progress; browser polls existing status without token persistence.
- Keep OFF-1/2 one-command convenience separated from authorized active probes, signed package/restore and physical airgap.
- Historical #270 stale branch remains closed without merge; #353 fail-fast is already merged; #355 actual workbook correction requires latest SHA CI and formal Codex Review before conditional merge.

## Archived History

- `.codex/archive/decisions.md-20261102-004437.md` — **verified exact Git-blob copy** of the full 16,600-character pre-compaction active decisions (blob `bdcc88ec04fa18f58647c3796502ae1dac61c6bd`). Detailed prior OFF-1A–T/SQL/ES/LLM, PR decisions and compatibility limits remain available without inflating active context.
- `.codex/archive/decisions.md-20261030-101300.md` — earlier verified full decision chronology, plus `decisions.md-20261021-165000.md`.
- **Compaction rule:** keep all operative/current decision boundaries in this summary; historic snapshots and superseded pending/review status live in the exact archived originals, not as current claims.


- **2026-11-02 OFF-2 direct dependency audit candidate:** a stdlib-only, bounded/no-follow local read of managed `requirements.txt` with fixed statuses/counts is preferable to invoking pip, guessing versions or treating VCS/direct URLs/markers as locked. Its allowlisted `release-deps` mode never establishes complete package provenance, full wheelhouse, Python/OS/native ODBC compatibility, physical airgap or restoration.

- **2026-11-02 OFF-2 Wheel verifier hardening candidate:** retain independently trusted external inventory digest and same no-follow wheel FD, then parse bounded ZIP central directory and two small textual metadata files to reject arbitrary bytes with a .whl extension. Never extract or execute Wheel payloads, and do not claim PEP 427/PEP 508/PEP 440/RECORD/platform ABI/dependency closure, signed bundles or air-gap installation.

- **2026-11-02 OFF-2 Wheel RECORD integrity decision (candidate):** make the *existing* out-of-band-pinned, no-follow `wheel-files` checker verify a strict subset of Wheel `RECORD` SHA-256 inventory against every supported ZIP file member using bounded streaming (2 MiB RECORD, 256 MiB per wheel, 512 MiB entire run). Treat `RECORD.jws/.p7s` as deprecated optional unlisted sidecars per packaging specification, never as validated signatures. No on-disk extraction, install, model invocation, new API authority, self-issued trust pin or claim of dependency closure/airgap. Unsupported SHA families return conservative INCOMPLETE.

- **2026-11-02 OFF-2 target ABI inventory decision:** a standard-library-only operator-invoked command through existing safe root Shell is the narrowest non-mutating way to collect Linux distribution, CPU, CPython SOABI, libc and configured ODBC18 registration from bounded nofollow files. Report fixed allowlisted non-secret fields only, never raw paths/hosts/users/credentials, native driver load or network. Mark missing/overridden ODBC config and untrusted target evidence INCOMPLETE, even complete observations remain PARTIAL/NOT_TESTED.

- **2026-11-02 OFF-2 conservative native binary header decision:** on observed Ubuntu22.04/CPython3.10 target, enhance existing `target-platform` v1 to v2, do not create a second service probe. Only parse registered ODBC18 Driver path privately; require exact approved Microsoft vendor root and versioned library basename, `O_NOFOLLOW` for all path components, bounded regular file and first 64 ELF bytes matching current CPU, ET_DYN/ELF64 little-endian. No `ctypes.CDLL`/dlopen/SQL, no reported raw path, checksum/signature or unknown distro inference; return `INCOMPLETE` for missing/mismatch. Even `PASS_PARTIAL` remains not native ABI/TLS/airgap attestation.

- **2026-11-02 ODBC dynamic metadata scope:** only inspect a strictly bounded ELF64 PT_DYNAMIC/DT_NEEDED string table via the same root-anchored O_NOFOLLOW ODBC18 file descriptor and preserve stable fstat; do not spawn ldd/ldconfig, search filesystem, load the .so, reveal DT_NEEDED strings or derive actual dependency resolution from them. Cap all file reads, return count/enum, fail closed for unsupported. Output schema v3 and PASS_PARTIAL semantics remain explicitly not release/airgap acceptance.
