# Known Issues

## 2026-09-10 Local pytest shim import-path limitation

- In the current Codex container, invoking the `pytest` shim directly for the combined Requirement launcher/worker regression set omitted the repository root from `sys.path`, causing collection-only `ModuleNotFoundError: requirement_scheduler` errors. The equivalent `python -m pytest ...` command uses the repository root correctly and passed all 144 selected tests. This is a local test-entrypoint limitation, not a production launcher or package failure.
- Package installation was attempted first as required. All requirements were already installed; the package-index proxy still emitted its known HTTP 403 retry warnings while checking for a newer pip release.

## 2026-09-09 Runtime-automation implementation environment

- Hosted `main` at `13ef7bf980614c986e7fd0a2756d779ccccb415f` was verified externally by Human/ChatGPT GitHub authority and matched the clean local baseline. Codex raw `git fetch` remains unavailable because the proxy returns CONNECT tunnel HTTP 403; no successful fetch is claimed.
- The schedule-worker repository implementation can be exercised with fakes and existing DB-API fixtures here. The authorized three-item automatic schedule → handoff → Report Job → DOCX deployment acceptance is NOT EXECUTED and remains operator-only.

## 2026-09-09 Hosted rebaseline unavailable for Plan/Prompt v1.1 correction

- The local repository had no configured Git remote (`git remote -v` returned no entries). `git fetch --all --prune` completed locally but could not query hosted `main`, so hosted state newer than local clean baseline `a702dcf528cd6f77f26aa89aec665dcc8145acda` could not be ruled out.
- Alternative evidence was the clean local merge commit for PR #226 plus exact repository/branch/HEAD/status capture. Plan v1.1 and Prompt v1.1 require future implementation to fetch and bind actual hosted `main`; no hosted-baseline claim is made by this documentation correction.

## 2026-09-08 Phase 1C live CHECK-expression blocker corrected in repository

- The Phase 1B post-PR #218 operator startup progressed past `RequirementStore.initialize()`; its prior DB-API row-container defect is no longer the active live blocker.
- Phase 1C live startup was executed by the operator and reproduced a canonical CHECK comparison failure caused by SQL Server moving `NOT` from `<column> NOT LIKE` to the equivalent `NOT <column> LIKE` catalog spelling. Focused repository tests now cover both artifact SHA-256 and semantic fingerprint constraints plus fail-closed semantic drift.
- The post-fix Phase 1C live SQL startup retest was not executed in this environment and remains pending operator execution. Repository verification cannot substitute for that live retest.

## 2026-09-08 Phase 1B live SQL acceptance blocker corrected in repository

- Phase 1B live SQL acceptance has now been initiated by an authorized operator. The pre-fix run proved connectivity, schema/table/constraint creation, catalog visibility, and transactional rollback, then reproduced canonical catalog validation failure caused by DB-API row-container equality semantics.
- The repository now normalizes catalog result rows before exact scalar comparison and retains fail-closed structural validation. A post-fix live SQL retest was not executed in this environment and remains pending operator execution.
- Full repository verification is not green: `python -m pytest -q tests/ -x` stops at `tests/test_batch_scheduler_security.py::test_phase0_harness_has_no_raw_key_literal` because a pre-existing tracked operator harness contains raw-looking key literals. The focused Requirement gates pass, and this correction neither reads nor modifies those literal values.
- Hosted refresh and PR publication are unavailable because this checkout has no configured remote and the GitHub HTTPS probe is rejected by the environment proxy with HTTP 403. The `pytest` shim also omits the repository root from its import path here, so verification uses the equivalent `python -m pytest` invocation.

## 2026-09-04 Phase 1B live SQL Server acceptance not executed (superseded)

- Historical status only. Live acceptance was later initiated and its current status is recorded in the 2026-09-08 entry above.

## 2026-09-03 Private deployment unreachable from Codex environment

- The configured operator smoke target returned the same HTTP 403 for health, missing/invalid credential, read-only credential, chat, and Report Job probes, indicating interception before the SRA application rather than an application security result.
- Fast live security smoke and the real Elasticsearch → long Agent → signed Word E2E are therefore NOT EXECUTED in this environment. Run the Plan v6.1 operator acceptance from a network that can reach the private deployment; do not classify the proxy response as an SRA failure.

## 2026-09-02 Phase 0 operational limits

- OpenWebUI's service principal identifies the integration, not an individual OpenWebUI end user.
- Service-key persistence is a single-machine owner-only file; it is not distributed state.
- Signed URLs are bearer capabilities until expiry and historical messages may contain expired links. Reverse proxies should omit/redact query strings in access logs.

## Current Summary

- Hosted `main` refresh and PR publication are unavailable in this checkout because GitHub access returns `CONNECT tunnel failed, response 403`; the local starting commit matched the requested baseline exactly.
- Python 3.10.20 is installed, but its isolated environment lacks the project dependencies. The package-index proxy returned HTTP 403 when installing `requirements.txt`; therefore only the dependency-free Python 3.10 compatibility-helper smoke ran, while full Requirement model/Pydantic and SRA API imports were verified on the provisioned default runtime.
- The current environment does not have Playwright / browser runtime. Visual UI changes cannot be verified with screenshots or browser E2E here; use static DOM / JS checks, node syntax checks, pytest, and a browser-capable environment when screenshots are required.
- Excel-to-SQL file ops may emit a Python datetime deprecation warning because `datetime.utcnow()` is still used. Existing tests pass; later work can migrate to timezone-aware datetime.
- FastAPI / Starlette TestClient may emit compatibility deprecation warnings. Existing tests pass.
- `python -m pip install --upgrade pip` may retry against the package index with a proxy / network 403. Existing requirements are installed and pytest can run; downloading new packages may require a network-enabled environment.

## Recent Changes

- 2026-08-21：代理人資料流程頁標題列導航調整仍受既有 Playwright / browser runtime 缺少限制，無法提供瀏覽器截圖；替代驗證使用共用導航 JavaScript syntax check、靜態 DOM assertions 與 FastAPI route test，22 tests passed。

- 2026-08-20：完整 test suite 有兩項既有失敗：`test_role_hierarchy_approval_and_role_options` 在整套執行時受 `api.*` / `sra_api.*` module reload identity 影響回傳 403（單檔執行 21 tests passed）；`test_vercel_json_uses_zero_config_fastapi_discovery` 期待 `auto`，但目前未修改的 `vercel.json` 為 `always`。本次 security targeted suites 全數通過。

- 2026-08-20: 此容器對遠端私有 Ollama 位址的 curl 經環境 proxy 回覆 HTTP 403，無法代替部署工作站驗證 `/api/chat`；已提供在 API 工作站執行的直接 curl 檢查方式，單元測試則驗證模型 override 與 timeout 傳遞。

- 2026-06-25: Editor mapping metadata UI screenshot limitation was recorded; substitute verification uses form-config tests, static UI tests, and JS syntax checks.
- 2026-06-25: pip index 403 retry was recorded; `requirements.txt` is currently satisfied, so py_compile, pytest, and node checks can run.
- 2026-06-22: Vercel mock preview login editor audit read-only filesystem issue was resolved by writing default Vercel/NOW audit logs under `/tmp/sra-auth/editor_audit.jsonl`.
- 2026-06-22: GitHub PR conflict issue was resolved; runtime source remains `sra_api/`, and top-level `api/` keeps only shim / Vercel entrypoint files.
- 2026-06-11 to 2026-06-22: Repeated Editor, portable auth pack, Excel-to-SQL dashboard / import center screenshot limitations were all due to missing Playwright and are archived in detail.

## Open Issues

### Retrieval exclusion directive is not propagated to the ES Tool

- First confirmed: 2026-08-31.
- Impact: Report Data Agent instructions can prevent an explicitly excluded term from being selected as a core term, but the downstream `es_search_news()` call receives only the prepared core query. Because the exclusion directive is not structured data at that boundary, the architecture cannot guarantee that synonym expansion will never produce the same excluded spelling.
- Mitigation: synonym expansion now uses full-query contextual disambiguation and a narrower equivalent-name contract; do not claim this is a hard exclusion guarantee.
- Status: Open.

### Playwright / browser runtime unavailable

- First seen: 2026-06-11.
- Impact: no screenshots, hover/touch browser verification, or Playwright E2E in this environment.
- Substitute: static UI tests, `node --check`, API / unit / integration tests; run browser validation elsewhere when needed.
- Status: Open.

### datetime.utcnow deprecation warning

- First seen: 2026-06-11.
- Impact: Excel-to-SQL tests may show a deprecation warning; tests still pass.
- Follow-up: migrate to timezone-aware datetime.
- Status: Open.

### FastAPI / Starlette TestClient warning

- First seen: 2026-06-12.
- Impact: tests may show Starlette TestClient / httpx compatibility warnings; functional tests pass.
- Status: Open.

### pip package index 403 retry

- First seen: 2026-06-25.
- Impact: current requirements are satisfied, but installing new packages may fail or be delayed.
- Substitute: use already installed dependencies for validation; install new dependencies in a network/proxy-enabled environment.
- Status: Open.

## Archived History

- `.codex/archive/known_issues.md-20260625-130126.md`: Archived all detailed known-issue entries from 2026-06-11 through this compaction, including repeated UI screenshot limitations, resolved Vercel / GitHub issues, and pip index 403 retry.

## 2026-07-03 pip index 403 during dependency preflight

- 在本環境執行 `python -m pip install --upgrade pip && python -m pip install -r requirements.txt` 時，`pip install --upgrade pip` 查詢 `/simple/pip/` 仍出現 `Tunnel connection failed: 403 Forbidden` retry，導致整條 chain exit code 為 1。
- 替代驗證：`requirements.txt` 的套件皆回報 `Requirement already satisfied`，並已成功執行本次相關 `node --check` 與 pytest 測試。

## 2026-07-04 UI 截圖驗證限制

- 本次調整 Editor 網站導航結構屬靜態 UI 變更；目前容器未提供可用瀏覽器 / Playwright runtime，無法產生實機截圖。
- 替代驗證：使用 `node --check sra_api/static/editor_bootstrap.js` 檢查導航 JS 語法，並以 `PYTHONPATH=. pytest tests/test_editor_auth_ui_static.py::test_editor_navigation_is_header_multilevel_and_collapsible -q` 確認代理人資料流程圖只保留於第一層、未出現在 Excel 匯入流程管理子層。
# 2026-09-01 Report Job deployment limits

- Worker 是單一 API process 內的 thread，SQLite 與 DOCX 都在 local disk；不可用多 process/多 machine 當作 HA。process crash 時正在執行的工作於下次 startup 轉為 `interrupted`，不會自動續跑或重試。
- pip upgrade 查詢仍因環境 proxy 403 retry，但 requirements 已安裝，未阻礙測試。

## 2026-09-03 Phase 0 live deployment acceptance unavailable

- 本容器對 tracked smoke harness 所設定的 private SRA API 呼叫均由環境 proxy 回覆 HTTP 403，無法證明請求抵達 SRA deployment；real Elasticsearch、long report Agent 與 signed Word E2E 因此 NOT EXECUTED。
- 替代驗證為 84-test Phase 0 targeted gate及 343-test full repository suite。部署 acceptance 與其後 credential rotation 仍須由可連線的 operator environment 執行；既有 working acceptance credentials 本輪刻意保持不變。
- Required Implementation Review v2 文件不在 actual repository；現有最新 review 是 v1，Plan v6 仍明確指定 v2。實作以 authoritative Design v3、Plan v6 completion delta 與 actual source 為準，待 operator 補回 review artifact 供追溯。

## 2026-09-04 Phase 1 deployment acceptance pending

- This environment has no verified private SRA/Elasticsearch connectivity or runtime Batch Scheduler credential. Real two-task CSV/JSON E2E, restart observation against a live remote job, DOCX content review, and replacement-key revocation were not executed. Repository transport-seam tests are the substitute validation, not deployment acceptance.

## 2026-09-04 Requirement SQL Server live acceptance unavailable

- No explicit authorized connection or credential for the intended Requirement control-plane SQL Server was provided in this environment.
- Substitute verification: recording fake-ODBC transaction/migration tests plus focused and full repository suites; these are repository evidence only and are not live SQL Server acceptance.
- Status: Open; execute the documented live acceptance from an authorized operator environment.

## 2026-09-04 Phase 1C live acceptance unavailable

- Phase 1C live SQL Server acceptance was NOT EXECUTED because this task supplied no explicitly authorized SQL Server connection or credential. Repository recurrence, fake persistence, API, security, and regression checks are substitute repository evidence only. Phase 1B live SQL acceptance independently remains NOT EXECUTED.
- `pip --upgrade` encountered the known package-index proxy HTTP 403 warning, but all requirement packages were already installed and dependency verification completed.

## 2026-09-04 Phase 1C-A lifecycle audit blocker

- Canonical lifecycle audit remains filesystem JSONL (`append_audit_event`) while schedule authority is SQL Server. A SQL commit and local filesystem append cannot be truly atomic with the existing architecture; an audit append failure can occur after an accepted SQL mutation. Resolving this requires a reviewed authority-boundary design (for example a transactional SQL outbox), not a local correction or distributed-transaction invention. Finding G and the Gate A closure are BLOCKED; Phase 1C-B must not start.
- Phase 1C and Phase 1B live SQL Server acceptance were not executed because no explicitly authorized SQL Server access was supplied. Repository fake-ODBC tests are substitutes only.
- Package installation observed package-index proxy HTTP 403 retries, but all requirements were already installed and verification could proceed.

## 2026-09-05 Phase 1C v3 closure remains unimplemented

- Design v3 resolves the authority decision on paper by selecting a transactional Phase 1C SQL outbox and at-least-once JSONL projection, plus canonical schema v2 migration and task-ID widening. The current runtime still has schema version 1, `phase1a_task_id NVARCHAR(128)`, and post-commit direct success audit, so the repository gate remains NOT PASS until the v3 closure is implemented, merged, and reviewed.
- Phase 1C-B remains blocked and NOT STARTED. Live Phase 1B/1C SQL Server acceptance remains NOT EXECUTED without explicitly authorized access.

## 2026-09-05 Phase 1C-A v4 live acceptance

- Live SQL Server migration/audit acceptance was NOT EXECUTED because this environment was not supplied an explicitly authorized SQL Server connection. Repository catalog/transaction/projector tests and compile/static checks are the substitute evidence; operator acceptance must still exercise both recognized v1 catalogs and projection retry against SQL Server.

## 2026-09-05 Phase 1C-A v5 verification limitations

- No Git remote is configured in this checkout, so `git fetch --all --prune` had nothing to fetch and hosted `main` ancestry could not be independently compared; local HEAD is merge `974be3555ca0bb4a4699cbe9b8758c08c02d2f04` containing PR #205.
- `pip --upgrade` encountered the environment's package-index proxy HTTP 403 retries, but all requirements were already installed and repository verification ran successfully.
- Live SQL Server fresh-v2/migration/rollback/projection acceptance remains NOT EXECUTED without an explicitly authorized connection. The comprehensive scripted DB-API suite is the documented alternative repository validation.

### 2026-09-05 Phase 1C-A v5 post-merge acceptance limitation

- Live SQL Server acceptance was NOT EXECUTED because no explicitly authorized connection details were supplied. Repository DB-API simulations, including non-tuple indexable rows and decorated SQL Server catalog expressions, were used instead and are not represented as live acceptance.
- `pip --upgrade` retried against the environment package-index proxy and received HTTP 403, but the required packages were already installed and `pip install -r requirements.txt` completed from the environment.

## 2026-09-05 Phase 1C-B planning hosted refresh limitation

- A GitHub `origin` was configured and `git fetch origin main` was attempted before planning, but the environment proxy returned `CONNECT tunnel failed, response 403`. The local starting commit exactly matched requested PR #210 merge `d1fc213633dc9dc83c1e32e010d9aca59a0dd909`, but a newer hosted `main` could not be independently excluded. The implementation gate must fetch/rebaseline from a network-enabled environment before executing Task 1; documentation/source checks used the exact local snapshot instead.

## 2026-09-07 Phase 1C-B acceptance limitations

- Live SQL Server acceptance: NOT EXECUTED; no explicitly authorized SQL Server environment was supplied.
- Private/deployment Report Job and DOCX E2E: NOT EXECUTED.
- Package index refresh returned proxy HTTP 403, but all requirements were already installed locally.
- This checkout has no configured Git remote, so hosted refresh/push/CI inspection is unavailable.

## 2026-09-07 Phase 1C-B closure external acceptance limits

- Live SQL Server schema-v3 migration, locking, fencing, and rollback acceptance is NOT EXECUTED because no explicitly authorized SQL Server connection was supplied. Repository DB-API simulations are not live evidence.
- Private Report Job + Agent + DOCX deployment E2E and hosted CI are NOT EXECUTED/NOT OBSERVED in this environment. The package index proxy returned HTTP 403 during the optional pip upgrade check, while installed requirements were sufficient for repository tests.
