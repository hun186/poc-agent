# Known Issues

## Current Summary

- Formal Requirement deployment acceptance is not complete. Repository tests and documentation review are not substitutes for authorized live SQL Server, Elasticsearch, external LLM, Agent, Schedule/Handoff, artifact, and DOCX verification.
- Live Requirement acceptance is specifically blocked by the unresolved Elasticsearch `mapping_incompatible` capability/mapping condition. Correct the live mapping issue and rerun authorized capability plus end-to-end acceptance before claiming deployment PASS.
- Unified launcher/deployment Gates SD-1 through SD-7 and real safe-restart/takeover behavior still require operator verification in the deployed SRA container.
- The execution environment may block direct Git/package-index network access through proxy/DNS restrictions. Hosted GitHub connector operations can still be available independently; installed requirements have allowed repository work when package downloads were unavailable.
- Browser/Playwright runtime is unavailable here; UI work can use static DOM/JavaScript/API tests but still requires browser-capable acceptance.
- Private Requirement SQL Server and SRA/Elasticsearch deployment credentials/configuration are not available in this repository environment.
- Direct `pytest` may omit the repository root from `sys.path` in this container; `python -m pytest` is the verified invocation style.
- Excel-to-SQL may emit `datetime.utcnow` deprecation warnings and FastAPI/Starlette TestClient compatibility warnings.

## Open Issues

### Requirement deployment acceptance

- Resolve live Elasticsearch `mapping_incompatible`, then rerun mapping/capability verification and the real Requirement → Schedule/Handoff → Report Job → Agent/LLM/Elasticsearch → DOCX flow.
- Run fresh/migrated SQL schema/catalog validation, rollback/failure injection, fencing/failover, concurrency/races, HA, credential rotation, and production content-quality acceptance in an authorized environment.
- The previously observed single-item and three-item technical Golden Paths do not close these broader matrices and must not be restated as fresh acceptance.

### Launcher and deployment lifecycle

- Run `./run_sra_api.sh` in the actual SRA container against the existing listener and verify the intended API process receives TERM, port 9002 is released, API/Schedule/Handoff replacements start, SQL lease authority remains correct, and no unrelated process is signaled.
- Manifest-enabled package/overlay trust-chain tooling exists, but live SD-1 through SD-7 evidence remains pending; do not retroactively bless an old deployment tree.

### Retrieval exclusion boundary

- Report instructions can keep an excluded term out of core-term selection, but downstream synonym expansion still lacks a structured exclusion contract. Contextual disambiguation is mitigation, not a hard guarantee.

### Runtime/provenance observation limits

- Python cannot safely inventory every dynamically loaded module in separate Schedule/Handoff worker processes without additional IPC/instrumentation. Current provenance positively binds managed runtime files and worker entry identities; stronger per-process loaded-module attestation requires separate design.
- Deployment-local Requirement SQL registry remains privileged configuration and is intentionally outside release-provenance contents/hash disclosure.

### Verification environment caveats

- Historical combined full-suite runs exposed order-dependent/pre-existing failures and launcher timing sensitivity while focused required suites passed. These records are preserved in archive; do not reinterpret them as a current full-suite PASS or current production defect without re-running on the relevant head.
- Remote/live operator execution requires valid ignored/process configuration for deployment URL, model, and authorized superuser session credentials. Do not substitute a Service Key where a user-session authority is required.
- Signed URLs remain bearer capabilities until expiry; service-key persistence and local Report Job SQLite/artifacts are not multi-machine HA.

## Recent Changes

- 2026-10-06: P1.0A PR #279 verification again confirmed direct Git transport is unavailable in this execution environment (`git ls-remote` failed with `Could not resolve host: github.com`). Therefore no local pytest PASS is claimed for this branch; Hosted review/check evidence remains required.

- 2026-10-06: P1.0 re-review again confirmed the execution container cannot resolve `github.com` for a direct clone, so local pytest could not be run on the hosted branch; Hosted GitHub connector inspection/checks remain available and must not be represented as local pytest.
- 2026-10-06: Restored the unresolved Elasticsearch `mapping_incompatible` blocker to active memory/known issues during PR #277 compaction review.
- 2026-09-30: Hosted GitHub connector remained usable for PR work while direct Git transport from the execution container was unavailable; no local pytest result was claimed for that corrective.
- 2026-09-22: Capability-adaptive E2E established offline boundary verification but did not perform FULL_LIVE/HYBRID deployment acceptance.
- 2026-09-16: Harness v2/provenance work retained explicit live-environment and cross-process observation limits.

## Archived History

- `.codex/archive/known_issues.md-20261006-153400.md` — complete active known-issues file immediately before this compaction, including all prior dated environment/deployment/provenance records.
- `.codex/archive/known_issues.md-20260910-070805.md` — earlier full pre-compaction known-issues history.
- Older archive references remain discoverable from those preserved files.

## Compaction Record

- 2026-10-06: Compacted active `.codex/known_issues.md` after robust date/work-block counting exceeded the AGENTS.md >20 trigger. Full text was archived first; unresolved acceptance blockers, environment constraints, retrieval limitation, launcher work, and provenance observation limits remain active.


- 2026-10-07: P1.2 local verification reconfirmed the execution container cannot resolve `github.com` (`git ls-remote` -> `Could not resolve host: github.com`). The hosted branch therefore cannot be cloned for local pytest; do not claim a local pytest PASS. Use Hosted source inspection, Vercel/check status, and exact-head Codex review for this slice.


- 2026-10-07: P1.3 local verification again cannot clone/read Hosted Git through direct transport because `github.com` DNS resolution fails. No local pytest PASS is claimed for the one-time create saga; Hosted source inspection, exact-head Codex review, and Hosted checks are the available repository verification evidence.


- 2026-10-08 P1.5 local verification remains unavailable because direct Git transport cannot resolve `github.com` in this execution environment. No local pytest PASS is claimed; use Hosted source inspection, exact-head Codex review, and Hosted checks for this branch.


- 2026-10-08 P1.5A local verification remains unavailable because direct Git transport cannot resolve `github.com` in this execution environment. No local pytest PASS is claimed; use Hosted source inspection, exact-head Codex review, and Hosted checks for this branch.
- 2026-10-08 The P1.5A low-level Schedule approval Product-ownership check is an intentional interim non-atomic precheck. A concurrent ownership/mutation TOCTOU remains until P1.6 introduces same-transaction locks/fences across low-level Schedule/source writes.

- 2026-10-11 P1.6 verification limitation: direct Git transport/local checkout remains unavailable in this execution environment, so no local pytest PASS is claimed. Current evidence is Hosted source/diff inspection plus focused regression additions; exact-head Hosted checks and Codex review are required before merge.

- 2026-10-12 P1.7: Product input replacement has focused in-memory/scripted-DB regression coverage and reuses Phase 1B snapshot CAS. Real two-connection SQL Server concurrency and live import acceptance are still pending; direct repository checkout/pytest is unavailable in this environment. Do not label these as PASS based solely on hosted Vercel/Codex review.

- 2026-10-12 P1.7 first exact-head Codex P1 finding: candidate-diagnostic CAS had a transaction gap before failed-import persistence. The branch now writes the preallocated failed import under the same Requirement-set UPDLOCK/HOLDLOCK transaction, with regression coverage for success, rollback, and stale-base refusal; exact-head re-review and actual SQL Server concurrency acceptance remain pending.

- P2.1 read/preview PR has code and scripted/API regressions but no claimed live SQL Server deployment or actual pytest PASS (GitHub runtime execution not verified). Cross-Task result sharing/semantic dedup is not implemented and requires a separate design/authorization/privacy gate.

- 2026-10-12 PR #288 review blocker: GitHub Codex bot explicitly reported `You have reached your Codex usage limits for code reviews` to the first review trigger and the exact-head `@codex review` request. No Codex assessment occurred, and Vercel preview checks do not substitute for it. Do not treat trigger/PR-open status as clean review; wait for review capacity or another explicitly accepted review gate. Direct git checkout also remains blocked by GitHub DNS resolution in container; pytest and live SQL acceptance remain unverified.

- 2026-10-12 P2.1 exact-head `3cf17b8` Codex completed and reported six findings (one P1 and five P2): pre-parser multipart disk exposure, direct JSON field-size mismatch, compressed XLSX and preview output amplification, eager Run Items, split Task/Schedule reads, and presenter-invariant errors mapped to 422. Remediation changes are on PR #288 and require exact-head Codex re-review; do not treat the previous findings as verified resolved yet. Direct git checkout still fails DNS resolution; no local pytest or live SQL Server acceptance is claimed.

- 2026-10-12 P2.1 Codex round 2 (`4141570`) completed with three new P2 findings: URL-encoded over-1MiB form field regression expected 422 instead of actual Starlette parser 400, JOIN without HOLDLOCK on a locking READ COMMITTED SQL Server, and unknown presenter KeyError incorrectly masked as 404. Corrected test/HTTP contract for framework 400, added HOLDLOCK to both joined authorities, and restricted 404 mapping to known not-found codes. Exact-head re-review and live SQL concurrent-read/pytest verification remain pending.

- 2026-10-12 PR #288 Codex review round three (head `9fa8890`) completed with three new P2 findings: XLSX matrix/value memory amplification despite row caps, N+1 per-Run SQL lookups in history lists, and a public Run Artifacts link whose route is not implemented in P2.1. The branch now includes XLSX total-cell/decoded-byte caps, joined single-query Run pages with inline status evidence, omission of deferred link and tests. These fixes still require a fresh exact-head Codex review, runtime pytest and actual SQL Server acceptance.

- 2026-10-12 PR #288 fourth Codex review on exact head `45318fd` completed with 2 P2 findings: valid-ZIP but structurally invalid XLSX could yield 500, and pre-parser HTTP 413 omitted CORS response headers. Changes added XLSX parser-error normalization to `source_format_invalid` at reader boundary, reordered middleware registration for CORS on early 413 responses, and added regressions. Fresh exact-head review and runtime pytest/live SQL Server acceptance remain unverified.

- 2026-10-12 PR #288 fifth exact-head Codex review `6dbcf20` completed with one P2: structurally invalid XLSX workbook XML (`sheetId` non-integer) makes openpyxl raise `TypeError`, incorrectly yielding Product 500. Corrected the XLSX-only `read_bytes` parser-exception boundary to normalize `TypeError` to `source_format_invalid` (422) and added a ZIP workbook-XML regression. The fixture's openpyxl TypeError was independently reproduced, but repository pytest, new exact-head Codex review and live SQL Server acceptance are still pending.

- 2026-10-12 PR #288 sixth Codex exact-head review at `1102b36` completed with one P2 finding: sparse CSV rows could create millions of source dictionaries because the HTTP row cap did not bound columns, total cells or decoded bytes. Reader now enforces preview-only 128-column, 50,000-cell and 8-MiB value-byte budgets for CSV; aligned JSON preview with the same budgets to avoid cross-format amplification, leaving P1 internal full import unchanged. Added positive/negative regressions. A new exact-head Codex review, executable pytest and live SQL Server acceptance are still needed.

- 2026-10-12 PR #288 seventh exact-head Codex review at `b9d4bd3` completed with a P2: even after total-cell caps, `json.loads` of an entire uploaded 10 MiB JSON array could materialize millions of dictionaries before the guard. Preview-only JSON now scans/decodes array entries incrementally with a 1 MiB per-entry parse bound and existing row/cell/byte caps; internal no-cap import remains unchanged. Added large-array and complex-string regressions. Fresh exact-head Codex review, executable pytest and live SQL Server acceptance remain necessary.

- 2026-10-12 PR #288 eighth Codex exact-head review at `e464208` completed with two P2 findings: per-JSON-object preparse budget counted Unicode code points instead of UTF-8 bytes, and the incremental array parser treated a top-level `}` as an accepted element delimiter. Corrected the 1 MiB bound to count encoded UTF-8 bytes before materializing each object and require exact `,` or `]` delimiters. Added CJK multibyte, malformed delimiter and valid-input regressions. New exact-head review and repository pytest / live SQL Server acceptance remain pending; no merge authorized.

- 2026-10-12 PR #288 ninth Codex exact-head review at `d72444b` completed with one P2: malformed JSON Unicode escapes containing isolated UTF-16 surrogate halves were accepted by `json.loads` but caused a `UnicodeEncodeError` in preview resource-budget accounting, incorrectly yielding HTTP 500. Added a narrowly-scoped catch around JSON row key/value encoding to normalize this untrusted-input error as HTTP 422 `source_format_invalid`. Tests cover top-level/nested surrogate keys and values, low surrogate, plus valid paired Unicode. New exact-head review, real pytest and SQL Server acceptance still pending.

- 2026-10-12 PR #288 tenth exact-head Codex review `dd2f296` completed with one P2: optional lxml XMLSyntaxError from malformed XLSX archive XML escaped the stdlib ParseError catch, returning HTTP 500 instead of 422 source_format_invalid. Reader now conditionally imports lxml.etree.XMLSyntaxError (falling back to stdlib ParseError when lxml absent) and normalizes it only at the XLSX upload parsing boundary. Added invalid [Content_Types].xml regression conditioned on openpyxl.xml.LXML. New exact-head Codex review and executable repository pytest/live SQL Server acceptance still pending.

- 2026-10-12 PR #288 eleventh Codex exact-head review on `4fe28ed` completed with one P1 and one P2: optional lxml XMLSyntaxError compatibility used a forbidden try/except-wrapped import (AGENTS.md line 400), and nested compact JSON values still expanded into millions of Python objects within the 1-MiB per-row byte cap. Replaced optional import with `importlib.util.find_spec` + `importlib.import_module` (no guarded import), and enforced JSON structural-token budgets of 5,000 per preview row / 100,000 across a preview while scanning *before* `json.loads(fragment)`. Tests cover oversized nested dicts, aggregate nested scalar arrays, normal nested strings and unchanged unbounded internal P1 reads. Exact-head Codex re-review, executable pytest, and real SQL Server acceptance remain pending.

- 2026-10-12 PR #288 twelfth Codex exact-head review at `a9449c6` completed with P1 valid multirow JSON parsing regression (structural-token `if` intercepted top-level comma) and P2 direct `requirements_json` form payload decoded via whole-value `json.loads` before bounded scanner. Moved the structure count after the outer-comma boundary check, and routed direct form JSON through `read_json_rows(..., max_rows=5000)` before constructing Python objects and before invoking Product service. Invalid direct syntax retains `requirement_preview_input_invalid`; oversized nested inputs return `requirement_preview_too_large`. New API and reader regressions added. Exact-head Codex re-review, executable pytest and SQL Server concurrency acceptance remain pending; do not merge.

- 2026-10-12 PR #288 thirteenth Codex exact-head review at `fc1e8ea` completed with three P2 findings: eager large/nested `task` form JSON before Pydantic validation, ZIP `ZipInfo` memory allocation preceding 2,000-entry XLSX preview cap, and blank XLSX header `StopIteration` incorrectly surfacing as HTTP 500. Fixed a 4,096 UTF-8-byte pre-JSON task metadata cap, bounded raw ZIP EOCD/central-directory walk before `ZipFile` allocation (including anti-forged-count scan), and explicitly reject missing/blank XLSX header as `source_format_invalid`. Added adversarial task payload, max-valid task, 2,001-member ZIP, forged-count ZIP, normal ZIP and blank workbook regressions. New exact-head Codex review, executable pytest and SQL Server runtime acceptance pending. PR open, no merge authorized.

- 2026-10-13 PR #288 fourteenth Codex exact-head review at `5ff11c6` completed with one P2: 4 KiB predecode `task` metadata cap rejected schema-valid maximum-length non-BMP fields serialized with JSON's default escaped surrogate pairs (~4,454 bytes). Increased the still-small predecode cap to 8 KiB, preserving bounded eager JSON handling while admitting the maximum declared field lengths. Added regression for both max-length Emoji-escaped fields and a nested invalid metadata body exceeding 8 KiB. New exact-head Codex review, executable pytest and real SQL Server acceptance remain pending. PR open, no merge authorized.

- 2026-10-13 PR #288 fifteenth exact-head Codex review at `b3f3e73` completed with one P2: CSV preview width validation occurred after `csv.reader` materialized whole lists for headers or data rows, allowing a 10 MiB million-column row to inflate memory before rejection. Added preview-only streaming logical-record width preflight that counts delimiters before calling csv.reader, accounting for quoted commas, escaped quotes and embedded newlines; >128 fields now rejects as `requirement_preview_too_large` before field-list allocation. Full Phase 1B CSV reader with max_rows=None still skips preflight. Added regressions monkeypatching csv.reader to fail if called for oversized header/data rows, normal quoted/multiline CSV, 128/129-field boundary and unchanged internal reader. Exact-head re-review, executable pytest and true SQL Server acceptance remain pending.

- 2026-10-13 PR #288 sixteenth Codex exact-head review at `f372756` completed with one P2: structurally readable XLSX archives containing zero declared worksheets make `workbook.active` return None; dereferencing worksheet preview columns otherwise resulted in HTTP 500 `persistence_error` rather than HTTP 422 `source_format_invalid`. Guard `sheet is None` before all worksheet access, close workbook and raise stable input validation code. Added realistic XLSX ZIP workbook.xml fixture with no worksheet declarations and verified openpyxl returns None for workbook.active. New exact-head review, full repository pytest and live SQL Server acceptance remain pending; no merge authorized.

- 2026-10-13 PR #288 seventeenth Codex exact-head review `7b064f5` completed with P2 missing Import Profile lookup. `get_profile_version` emits `KeyError("profile_version_not_found")` for a client-supplied nonexistent `profile_version_id`, which previously escaped as masked HTTP 500. Preview service now narrowly maps precisely this known KeyError to 422 `requirement_preview_profile_invalid`; unexpected storage/presenter KeyErrors remain HTTP 500, not misrepresented as absent user selections. Added HTTP and service regressions for missing/unknown keys. Fresh exact-head Codex review and actual repository pytest and live SQL Server concurrency tests still pending, no merge.

- 2026-10-15 air-gap OFF-0 design limitation: existing Requirement E2E `offline` mode may use scoped mock ES/LLM and does not prove an air-gapped FULL_LIVE production dependency chain. Existing smoke helper `operator_e2e/p21_api_smoke.py` was deployed manually but not found on Hosted main. No full offline wheelhouse/ODBC/model/index bundle, read-only SQL catalog probe, unified CLI or site-level isolation evidence has yet been implemented. The OFF-0 JSON registry is contract-only, and its validator/test suite still requires checkout-time execution and review.

- 2026-10-15 PR #291 Codex P2 findings from initial reviewed head addressed on subsequent commits: contract now includes mandatory report redaction policy and safe output builder; worker Runtime Evidence dependency includes release provenance; malformed unhashable schema fields produce stable `ContractError` instead of traceback. Hosted OFF-0 tests/Codex re-review not yet claimed as PASS until exact-head evidence. Running GitHub Actions during development is NOT equivalent to successful offline deployment or a FULL_LIVE production dependency probe.

- 2026-10-15 OFF-0 PR #291 second Codex review identified P1 CI dependency setup and two P2 schema/output robustness findings. Changes are proposed on the same review branch; latest-head CI and subsequent Codex review must be checked. Even if GH Actions passes after `requirements.txt` install, OFF-0 only validates static contract/sanitized report construction, not actual SQL/Elasticsearch/LLM, worker, or DOCX services in an air-gapped site. Vercel deployment is separately blocked by daily build quota (`api-deployments-free-per-day`).

- 2026-10-15 third review of OFF-0 PR #291 identified three more P2 issues: credential/path/Unicode redaction bypass, deep-JSON recursion traceback, nonregular/size-race unbounded registry read. Remediation committed to the same branch with negative tests, but latest-head CI and Codex re-review are not yet proof of completion. OFF-0 remains contract-only and does not authorize actual offline dependency acceptance.

- 2026-10-16 OFF-0 PR #291 fourth Codex review found three P2 contract integrity gaps: deep JSON behavior differed across Python versions, error codes allowed contradictory FAIL/SKIP status, and missing checks could still yield contract PASS. Fixes and regression cases have been committed to PR branch; latest-head hosted tests/re-review remain pending. OFF-0 is not operational air-gapped acceptance.

- 2026-10-16 OFF-0 PR #291 fifth review: contract code previously allowed planned checks to return FAIL/WARN despite having no implemented probe. Branch now enforces SKIP/check_not_implemented exclusively until the check's reviewed readiness is updated. Await the exact-head CI and next review; do not label OFF-0 a live offline verification runner.

- 2026-10-16 OFF-0 PR #291 sixth Codex review: mutable registry readiness could falsely promote unimplemented checks to eligible PASS; in-code readiness binding and regression tests have been added to the branch, pending hosted exact-head CI and re-review. This is still a contract-only PR; real air-gap dependency probes and full-live acceptance remain unimplemented.

- 2026-10-16 PR #291 seventh Codex review found two P2 contract trust issues: changing JSON execution mode/effect/dependency graph could run acceptance E2E in Quick, and changing error codes could misdirect remediation. Branch now pins reviewed semantics and failure codes for every check ID, awaiting latest-head CI and Codex review. This does not yet provide actual offline dependency probes.

- 2026-10-16 OFF-0 eighth Codex review: even reusable existing components could report a fake PASS without executing a real probe. The OFF-0 report constructor now blocks per-check PASS until OFF-1 introduces actual reviewed execution/evidence bindings; safe schema validation continues independent of runtime acceptance. Current-head CI and re-review still required, and no operational air-gap probe is delivered by this change.

- 2026-10-16 OFF-0 ninth Codex P2: false FAIL/WARN could be reported with no real probe execution. Fix now rejects all runtime outcome claims (PASS/FAIL/WARN) in the OFF-0 safe record constructor until OFF-1 supplies audited probes and evidence. Exact-head CI/Review required; OFF-0 is not an executable production health check.

- 2026-10-16 PR #291 tenth Codex finding: contract-only SKIP records could contain fabricated yet syntactically permitted FULL_LIVE/hash/HTTP evidence. Branch now rejects nonempty SKIP evidence and tests all declared safe-value categories. Hosted tests and new Codex review are still needed. No actual air-gapped runtime probes have been delivered.

- 2026-10-16 OFF-0 PR #291 eleventh Codex finding: SKIP reasons remained forged despite redacted/empty evidence; API-01 wrongly allowed blocked_by_dependency/auth_session_unavailable. Current branch now permits only SKIP(check_not_implemented) until OFF-1/3 can bind specific reasons to actual checked dependencies/session/mode. Hosted CI and exact-head Codex review remain necessary.
