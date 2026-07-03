# Known Issues

## Current Summary

- The current environment does not have Playwright / browser runtime. Visual UI changes cannot be verified with screenshots or browser E2E here; use static DOM / JS checks, node syntax checks, pytest, and a browser-capable environment when screenshots are required.
- Excel-to-SQL file ops may emit a Python datetime deprecation warning because `datetime.utcnow()` is still used. Existing tests pass; later work can migrate to timezone-aware datetime.
- FastAPI / Starlette TestClient may emit compatibility deprecation warnings. Existing tests pass.
- `python -m pip install --upgrade pip` may retry against the package index with a proxy / network 403. Existing requirements are installed and pytest can run; downloading new packages may require a network-enabled environment.

## Recent Changes

- 2026-06-25: Editor mapping metadata UI screenshot limitation was recorded; substitute verification uses form-config tests, static UI tests, and JS syntax checks.
- 2026-06-25: pip index 403 retry was recorded; `requirements.txt` is currently satisfied, so py_compile, pytest, and node checks can run.
- 2026-06-22: Vercel mock preview login editor audit read-only filesystem issue was resolved by writing default Vercel/NOW audit logs under `/tmp/sra-auth/editor_audit.jsonl`.
- 2026-06-22: GitHub PR conflict issue was resolved; runtime source remains `sra_api/`, and top-level `api/` keeps only shim / Vercel entrypoint files.
- 2026-06-11 to 2026-06-22: Repeated Editor, portable auth pack, Excel-to-SQL dashboard / import center screenshot limitations were all due to missing Playwright and are archived in detail.

## Open Issues

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

## 2026-07-03 UI 截圖限制

- 本環境未提供瀏覽器 / Playwright runtime；本次代理人資料流程 SVG 靜態頁未做實機截圖。替代驗證為 HTML 靜態內容檢查、`node --check sra_api/static/editor_bootstrap.js` 與 FastAPI TestClient route 測試。
