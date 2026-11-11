# API Contract — SRAF (active, compacted 2026-11-11)

## Current Summary

### API identity, security and ownership
- FastAPI routes are implemented in `sra_api/routers/` with `api/` compatibility. Existing health/model/chat/report/document/product APIs use configured auth/RBAC, tenant-owner isolation, signed capabilities and no fake success responses.
- Public/Report services include `GET /healthz`, `GET /v1/models`, `POST /v1/chat/completions`, synchronous DOCX export, owner-scoped `POST /v1/report/jobs`, `GET /v1/report/jobs`, `GET /v1/report/jobs/{job_id}` and `GET /v1/report/jobs/{job_id}/word`. Report status/progress fields describe real durable Job phases, not invented progress or provider timeouts. Creation's existing `Idempotency-Key` binds owner+canonical request; ambiguous browser retries keep the same key/body and are user-triggered only.
- Requirement imports, immutable Set/Version/Snapshot, authorized Schedule/Handoff, Product v4 Task/Run APIs and Profile/Preview require their existing roles/CAS/idempotency constraints. Existing preview `POST /v1/requirement-task-previews` normalizes one bounded file/JSON input and does not persist/activate. Product browser is not authority for SQL writes.
- The operator superuser `GET /v1/operator-e2e/runtime-evidence?verification=release|functional` and `.../status` emit controlled local evidence, with process-local plan/generation and sanitised failure categories. OFF-0/1/2 partial diagnostics are not external signed release/FULL_LIVE acceptance; no normal startup preflight or automatic credentialed probes.

### GET /v1/editor/search — proposed additive #398 / PR #400 change (NOT MERGED)
- Authentication: existing `current_user`, `ensure_allowed_index(index)`, mock-preview access isolation. No new write permission. Required `index` (must be allowlisted); optional `q: str=""` (**no newly introduced max length**, original long-text search remains accepted); `size: int=20` 1–200; `page: int=1` >=1; `start_ts: str=""`, `end_ts: str=""` ISO8601 strings as before.
- New optional `search_mode: "auto"|"text"|"contains" = "auto"`; invalid modes produce FastAPI HTTP **422**. Empty/whitespace `q` uses the previous `match_all` behavior.
- Search fields still come from the per-index allowlisted Editor schema. Full text uses mapped root/nested `simple_query_string`, `default_operator="and"`, and configured boosts. Mapping `nested` path boundaries are respected, including nested children under an outer nested parent. Displayed `rawInfo.title` is now a default schema search field.
- `search_mode=text`: full-text only, **no substring wildcard**. `auto`: additionally attempt a keyword literal substring only if the stripped `q` is a **single 4–64-character alphanumeric/underscore/hyphen token containing underscore**; other searches behave as ordinary full text. `contains`: additionally attempt a literal substring for valid single 4–64-character token without requiring underscore. The `q` text is treated literally for this extra wildcard, not accepted as client wildcard syntax, and only configured `title`, `subject`, `uuid`, `rawInfo.title`, `communication.subject`, `multidim_event_json.article_title` keyword/wildcard or `.keyword` multi-fields are eligible (at most six); full article bodies are never leading-wildcard scanned. If metadata/keyword is unavailable or literal invalid, the original text query remains and a sanitized `warnings` entry explains no guaranteed substring support.
- Mapping/type metadata is read-only from ES and may be unavailable; non-searchable configured fields are excluded when Mapping known, with match_none and warning if none remain. `start_ts`/`end_ts` range applies to `schema.search_date_field` or default `importDT` (**import time**, not automatically article/event time), same as existing behavior. Result sort is date desc then _score.
- Response JSON retains `{hits:[{id,index,score,source}],total,size,page,has_more,warnings,mock_mode}`. `_source` is schema `search_source_fields` allowlist, not the full searched text; warnings already existed and now may additionally mention substring limits, mapping absence, expensive query. No change to the existing pagination or write endpoints.
- **Not an operational promise:** leading wildcard on large keyword dictionaries can be expensive or rejected by `search.allow_expensive_queries=false`. Live `news_test` index Mapping/query behavior, nested matches and p50/p95 latency have NOT been validated; no Mapping changes, bulk reindex, or automatic production rollout is authorized. This candidate remains unmerged until exact-head CI/formal Review and security/performance gates.

### Operator no-network CLI (not HTTP endpoints)
- `1_完整診斷驗收_SRAF.sh` L0/L1 and separately opted-in L2/L3 carry explicit partial/sensitive boundaries. OFF-1S strict listener/socket identity must precede Bearer. OFF-1B strict CA/IP SAN is authoritative for TLS identity; #396 operator-only CA+SAN-WARN does **not** change production runtime TLS contract and is pending separate approval. No claimed cross-host plan or release signing.

## Recent Changes

- 2026-11-11 Editor #400 adds optional search mode and Mapping-aware query assembly, while removing an initially proposed breaking 256-character `q` limit after formal Codex P1; latest-head CI/re-review pending.
- 2026-11-11 #395 Event/Timeline date semantics merged; actual ES and DOCX observation still pending.
- 2026-11-11 #396 special SAN warning operator diagnostic remains open and is not an accepted production TLS identity change.

## Archived History

Full previous active API contract is preserved verbatim in `.codex/archive/api_contract.md-20261111-200000.md`, independently re-fetched with identical SHA `3ca0b353bac76615fa2aaa336b7c5d2e0ab3c313`. Historical endpoint versions, proof scopes, previous candidate states and earlier compactions remain in archives; current Hosted SHA always prevails.
