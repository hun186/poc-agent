# Known Issues — SRAF (active, compacted 2026-11-11)

## Current Summary and Release Truth

- Hosted tests, OFF-0 (19 schema checks), OFF-1/2 partial observations and operator L0/L1 `PASS_PARTIAL` **do not** attest private FULL_LIVE Requirement→Schedule/Handoff→Agent/LLM/ES→Report Job/DOCX, trusted signed release, complete Wheelhouse or physical airgap/restore. Do not promote `production_release_ready` from partial evidence.
- Production SQL Server ODBC18 native load, real read/write permissions and schema, ES Mapping, TLS identity, local Ollama model generation, Worker lease/handoff and browser/DOCX remain independently unverified unless an operator supplies current live evidence. Runtime credentialed tests and writes require explicit separate authorization.
- The deployed Linux installation is an incremental Windows Robocopy/7z archive overlay (no Linux Git checkout). Deleted GitHub files, including old root `0_一鍵快檢_SRAF.sh`, may remain on disk. Validate the unified `1_完整診斷驗收_SRAF.sh` before manual cleanup; never auto-delete unknown deployed content.
- Provenance checks require independently reviewed manifest hashes, safe module/load identities and nofollow private output paths. Tool `PASS_PARTIAL` does not prove full transitive dependency lock, wheel/native library ABI, airgap install/upgrade/rollback or restore. The direct `requirements.txt` pins still include `>=`; do not guess frozen versions.
- OFF-1S strict exclusive listener/socket proof before bearer remains distinct from passive process observations. Linux same-host locks are **not** cross-host transaction/permission guarantees. Time budgets are cooperative and cannot forcibly cancel blocked provider calls. Logs must not expose credentials, raw Evidence/LLM prompts, internal resource paths or secret IDs.

## Current High-Priority Open Issues

- **#393 P0 Event/Timeline dates:** PR #395 was merged into main on 2026-11-11; #394 closed without merge. Source-local Event IDs, precision, query refill and incomplete-report guards exist in code, but real private `news_test` Mapping, timezone offsets, nested associations, high-volume paging and LLM/DOCX correctness remain NOT TESTED. Neither publication date nor an unrelated Event may be substituted for rejected Evidence.
- **#396 sensitive TLS policy (OPEN):** read-only operator date probe may warn about a CA-verified but IP-SAN-unmatched ES endpoint and continue GETs with Basic authentication. A valid CA chain does not prove intended IP peer identity; the special diagnostic must never be accepted as production TLS trust. Formal security review and high-risk operator approval are separate from completed general code review/CI.
- **#397 P1 Evidence trace and adaptive selection:** current ES `inner_hits.size=3`, parser source-vs-inner selection, strict-to-relaxed only at zero and report 120-snippet limit can hide relevant snippets. Need bounded reason-code trace, candidate conservation, date-safe low-volume refill, deterministic coverage/token budget and real five-to-one benchmark. No extra LLM until separately justified.
- **#398 P1 Editor query (PR #400 OPEN):** nested/root `simple_query_string` did not guarantee underscore substrings, UI hid index Mapping warnings and `rawInfo.title` was display-only. Candidate mapping-aware and bounded `*literal*` query is not verified live; may be slow on large keyword dictionaries or blocked by `search.allow_expensive_queries=false`. Text without keyword multifield cannot guarantee substring search. Ensure both nested parent/child layers in live mapping. No live Mapping writes or reindex; a future ngram migration requires separate approval.
- **#399 P1 conditional LLM evidence expansion:** only after deterministic #397 baseline and budget/coverage evidence; avoid unbounded calls/cost.
- **#290 disconnected deployment:** isolated wheel dependency closure, native ODBC, signed provenance, actual one-way rollouts, full E2E and OFF-5 restore remain pending.

## Current Operator Validation Gates

1. Check latest reviewed source/release bytes, active module identities, authorized API process/socket and private redacted evidence root before credentialed probes.
2. For Editor #398, run read-only literal full title / prefix / internal substring / no-match / nested / rawInfo.title / UUID tests on each target index; record mapping field types, `query.allow_expensive_queries`, total hits and p50/p95 latency. Do not claim full-index recall from synthetic fixture.
3. For Event/Timeline, validate date precision, event ID offsets, two-page results and report/DOCX warnings using source-local Evidence; **never** perform private ES writes without separate approval.
4. Verify browser owner isolation and signed, authenticated report downloads; obtain independent native SQL/ES/LLM live traces and complete package install/recovery evidence before production acceptance.

## Recent Change

- **2026-11-11 #400 candidate:** typed ES multifields and nested outer/inner query contexts added after formal Codex findings; latest-head Hosted CI and formal re-review PENDING. No real index performance or private Linux verification claimed.

## Archived History

Full pre-compaction file archived at `.codex/archive/known_issues.md-20261111-200000.md` (verified identical blob SHA `9778341e6f36db0381ae83cd4fec476513ae34a7`). Earlier archives retained. Historical PR-specific candidate statuses in the archive are not current Gate evidence.
