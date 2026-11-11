# System Architecture — SRAF (active, compacted 2026-11-11)

## Current Summary

### Runtime and data authority
- Main ASGI/FastAPI system `app.py`/`sra_api/` (with `api/` compatibility): real Agent/LLM, Elasticsearch retrieval/refinement, SQL Server requirements and ingestion, DOCX/Word reporting. `agent/` owns question parsing/search/Evidence/report; `data_ingestion/` owns imports; `sra_api/routers/` handles HTTP and RBAC.
- SQL Server immutable Requirement Set/Version/Snapshot/Profile/Import Run is authoritative. `requirement_scheduler/` and `sra_schedule/` own versioned Schedule/Handoff leases and worker execution. API lifespan Report Job Worker and launcher-managed Schedule/Handoff Workers are distinct; **do not** introduce a second queue. Existing SQLite ReportJobStore persists owner-scoped Job status/phases, not Requirement SQL authority.
- Roles `data_reader`, `data_editor`, `db_operator`, `superuser`, Service Keys, signed action capabilities and owner checks remain privilege boundaries. Product v4 task activation uses CAS/idempotency/fencing; artifact downloads require revalidation and strict path confinement. No fabricated successes or synthetic production API.
- Report Agent pipeline feeds real ES Evidence to the LLM, then validated DOCX; temporal Evidence from canonical #395 `agent/es/event_time.py` / `agent/tools_es/date_refill.py` ties Event and Timeline dates to source block-local event IDs and marks non-exhaustive searches. Bounded candidate refill is not a PIT snapshot; output must preserve date completeness warnings. Actual private `news_test` verification remains outstanding.

### Editor search (Issue #398 candidate, not merged)
- `sra_api/routers/editor.py` owns existing `GET /v1/editor/search` (allowed index, authenticated reader, optional `q`, `search_mode`, ISO date range, bounded pagination; existing response envelope and source fields). `sra_api/services/editor_form_config.py` provides per-index configured search fields/source projection; `sra_api/services/editor_index_utils.py` reads Mapping metadata including field/multifield type and nested parent paths.
- New `sra_api/services/editor_search_query.py` constructs nested-aware root/child ES DSL; a nested child under a nested outer object must enter **both** nested contexts. Root text matching uses mapped `simple_query_string`; specified title/subject/UUID keyword fields can add safe bounded literal substring conditions. Auto mode only for underscores, explicit contains available, text-only remains. Warnings flag absent Mapping/keyword and expensive substring limitations. **No ES Mapping modifications, reindex or production report-query changes.**
- `sra_api/static/editor_documents.js` only sends query/mode, shows returned warnings and renders existing safe projected hits; `sra_api/static/editor.html` exposes search mode. No bypass of RBAC or raw ES query injection. New `tests/test_editor_search_query.py` plus Hosted `.github/workflows/sraf-editor-search.yml` cover synthetic Python3.10/3.11 DSL/API/UI and Node syntax. No private ES performance verification yet.

### Operator, packaging and trust
- `tools/sraf_airgap_off1_hub.py`, `scripts/diagnostics/`, `1_完整診斷驗收_SRAF.sh` and OFF-1S/1B/2 diagnostics provide conservative L0–L3 opt-in stages. L0 no-network; L1 TCP/health partial; L2 private credentialed SQL/ES/LLM; L3 Report Job or real Requirement Harness only on separate explicit authorization. Privileged bearer checks require strict exclusive local socket proof; imported `pyodbc`/`dotenv` must not suppress safe passive diagnostic imports.
- Runtime `shared/runtime_provenance.py`, `REQUIREMENT_E2E_PROVENANCE.json`, `tools/deployment_manifest_policy.json` and OFF-2 nofollow pin/Wheel metadata/hash validators cover reviewed *selected* bytes only. They do not provide an independently trusted transitive Wheelhouse, native ODBC loading, signed model/source provenance, physically disconnected deployment, FULL_LIVE acceptance or OFF-5 restore.
- Private Linux deployments are **one-way Windows Robocopy/7z incremental overlays**, not Linux Git checkouts. Diagnostic sidecar ZIPs are independently built/reviewed on Windows/Hosted and extract without overwriting running SRAF. Deleted tracked root scripts may persist in deployed dirs and need intentional operator inspection.

## Recent Changes and Open Handoffs

- 2026-11-11 #395 Event/Timeline Evidence/report semantics merged into `main`; private date/ES/LLM/DOCX checks remain NOT_TESTED.
- 2026-11-11 #396 independent operator-only CA verified SAN warning branch has reviewed code but separate security and high-risk merge authorization remain outstanding.
- 2026-11-11 #400 Editor search candidate on isolated PR branch: latest-head Hosted CI/Codex and actual large-index keyword/nested/latency acceptance remain PENDING. Main behavior unaffected until Merge.

## Archived History

The complete previous architecture and all older data-flow/release decisions are preserved verbatim in `.codex/archive/architecture.md-20261111-200000.md` (identical Git blob SHA `f4637f782b33c39c410eff822fd1bc6a44d6c80b`). Previous archives are retained. Refer to active code/Hosted GitHub for current status, not archived candidate claims.
