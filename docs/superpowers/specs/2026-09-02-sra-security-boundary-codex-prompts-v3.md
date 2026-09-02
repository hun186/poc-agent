# Codex Prompt — v3 Final Re-Review Before Implementation

```text
請先不要修改程式碼。

v2 review 只剩一個 blocker：Report Job table rebuild 的 rename/index/drop/version 順序不夠精確。
現在請審查：

docs/superpowers/specs/2026-09-02-sra-unified-api-security-boundary-design-v3.md
docs/superpowers/plans/2026-09-02-sra-unified-api-security-boundary-plan-v3.md

請聚焦確認最後 blocker 是否已消除：

1. legacy Job DB 明確為 PRAGMA user_version=0；Phase 0 owner-aware schema為1。
2. fresh DB直接建立 version 1。
3. existing DB migration在單一 BEGIN IMMEDIATE transaction中固定為：
   validate legacy
   → create report_jobs_new
   → copy rows
   → validate staged rows
   → rename old report_jobs to report_jobs_old
   → rename report_jobs_new to report_jobs
   → 此時才建立 partial owner-scoped unique index
   → validate canonical schema/index/rows
   → drop report_jobs_old
   → set user_version=1
   → verify version
   → commit
4. partial index不可能誤建在 legacy table。
5. rollback failure injection至少涵蓋：
   - copy/validation
   - first rename
   - index creation
   - user_version update/verification
6. rollback後 legacy table、rows、global idempotency uniqueness、user_version=0 都完整保留。
7. Task 15 static namespace guard已改用 rg，並檢查：
   - sra_api.security.*
   - sra_api.services.auth_store
   - sra_api.routers.editor_dependencies
8. v2已通過的其他 security contract沒有被弱化。
9. 前次已確認 Task 0 root cause為 editor_dependencies capture stale AUTH_STORE；不得降低既有 RBAC assertion。

只回覆：
- 是否仍有 blocking issue
- migration ordering是否無歧義
- 是否可正式進 implementation
- 若有 blocker，列精確位置

若無 blocker，最後明確寫：
「可依 Phase 0 v3 計劃實作」

此階段不要修改 code。
```

# Codex Prompt — v3 Implementation

```text
請依 approved Phase 0 v3 文件完整實作：

docs/superpowers/specs/2026-09-02-sra-unified-api-security-boundary-design-v3.md
docs/superpowers/plans/2026-09-02-sra-unified-api-security-boundary-plan-v3.md

開始前依 AGENTS.md 載入 .codex 專案記憶。

Task 0 是 blocking prerequisite：
先修復 Editor auth stale AUTH_STORE/module-identity baseline，不得降低既有 superuser RBAC assertion。

Job migration必須嚴格依 v3：

LEGACY: PRAGMA user_version = 0
TARGET: PRAGMA user_version = 1

單一 BEGIN IMMEDIATE transaction：

1. validate legacy report_jobs
2. create report_jobs_new
3. copy rows with explicit columns
4. validate staged rows
5. ALTER TABLE report_jobs RENAME TO report_jobs_old
6. ALTER TABLE report_jobs_new RENAME TO report_jobs
7. only now create:
   CREATE UNIQUE INDEX uq_report_jobs_owner_idempotency
   ON report_jobs(owner_kind, owner_id, idempotency_key)
   WHERE idempotency_key IS NOT NULL
8. validate canonical schema/index/rows
9. DROP TABLE report_jobs_old
10. PRAGMA user_version = 1
11. verify version == 1
12. COMMIT

任何 exception都 rollback。

Failure injection至少測：
- copy/staged validation
- first rename
- partial index creation
- user_version update/verification

每種 rollback後必須證明：
- legacy report_jobs仍可用
- original rows完整
- old global idempotency uniqueness仍有效
- user_version仍為0
- 無 half-migrated canonical schema

Fresh DB直接建立 version 1。

Canonical runtime namespace仍為 api.*。
靜態 guard必須使用 rg：

rg -n 'from sra_api\.security|import sra_api\.security|sra_api\.services\.auth_store|sra_api\.routers\.editor_dependencies' sra_api tests api

其餘全部依 v3 spec/plan：
- AuthPrincipal/scopes
- OpenWebUI service key
- service-key cross-process locking
- Job owner isolation
- optional_principal + authenticated-or-signed resolver
- exact signed capability binding
- production signing-secret fail closed
- CORS/docs policy
- SQL injection/IDOR/path traversal/secret leak tests
- docs與.codex更新

不要實作 Batch Scheduler、Windows GUI、Server Dashboard。

採 TDD task-by-task。

完成後必須跑：
1. all targeted security tests
2. affected API regression tests
3. PYTHONPATH=. pytest tests -q --tb=short
4. python -m compileall sra_api
5. git diff --check
6. canonical namespace rg guard
7. service-key concurrent-process mutation test
8. Job migration success + rollback failure-injection tests
9. credential/sig leak review
10. manual no-key/OpenWebUI-key/Batch-key/revoked-key/signed-link smoke tests

最後回報 exact pass/fail counts；未執行測試不得宣稱成功。
```

# Codex Prompt — v3 Post-Implementation Security Review

```text
請不要新增 Batch/GUI 功能。

針對 Phase 0 v3 做 adversarial security review。

除既有 Phase 0 security項目外，特別檢查：

1. fresh DB是否直接 user_version=1。
2. legacy version=0是否只 migration一次。
3. partial owner-scoped index確定建在 rename後的新 canonical report_jobs。
4. migration任一步 failure是否 transaction rollback。
5. copy、rename、index、version failure後 reopen DB是否仍為完整 legacy state。
6. 是否可能留下 report_jobs_new/report_jobs_old 造成 initialize誤判。
7. owner-scoped idempotency是否真的取代 global uniqueness。
8. concurrent initialization是否被 BEGIN IMMEDIATE 正確序列化。
9. canonical namespace rg guard是否乾淨。
10. Task 0 stale AUTH_STORE combined-suite regression是否存在且會防止復發。

並重做：
- auth bypass
- scope escalation
- service-key leak/concurrency
- Job IDOR
- signed URL substitution/tampering
- invalid Authorization + valid sig fallback
- SQL injection/path traversal
- production secret fail-open
- query capability logging exposure

回覆：
- Critical / High / Medium / Low findings
- reproducible steps
- affected files/endpoints
- exact tests run/results
- required fixes

若沒有 blocking/high finding，最後明確寫：
「Phase 0 v3 security gate passed」
```
