# Codex Prompt — v4 Phase 0 Continuation Preflight

```text
你現在不是重新設計 Phase 0，而是接續目前已完成一大部分的 implementation。

在修改任何 code 前，完整閱讀：

1. docs/superpowers/specs/2026-09-02-sra-unified-api-security-boundary-design-v3.md
2. docs/superpowers/reviews/2026-09-02-sra-unified-api-security-boundary-implementation-review-v1.md
3. docs/superpowers/plans/2026-09-02-sra-unified-api-security-boundary-plan-v4.md
4. AGENTS.md
5. .codex/memory.md
6. .codex/backlog.md

Baseline 規則：

- ChatGPT review baseline 是 poc-agent_20260902-203534.zip。
- 該 ZIP 沒有 .git metadata，所以不要把 branch/commit 寫死成猜測值。
- 你目前所在 repository 的實際 source code、branch、HEAD commit 才是執行 baseline。
- 先執行 git branch --show-current、git rev-parse HEAD、git status --short 並記錄。
- 若目前 source 已比 Review v1 更新，實際 source 優先；不要把已修好的項目退回舊寫法。

角色限制：

- 你是 implementation agent，不是產品需求或架構重新定義 agent。
- Design v3 仍是 approved architecture。
- Plan v4 是從目前半成品往下補齊的 continuation plan。
- 不要因 Plan v3 checkbox 未勾就重做已存在的 AuthPrincipal、service-key store、owner migration、signed URL 等骨架。
- 除非 Design v3 無法實作，否則不得自行重新設計 architecture。
- 不得默默弱化 authentication、authorization、scope、owner isolation、transaction、rollback、validation、audit、error handling 或 secret handling。
- 不實作 Batch Scheduler、Windows GUI、Server Dashboard、Redis/Celery/PostgreSQL、OIDC/OAuth。

先只做 preflight：

1. 對照 Review v1 的 Blocking/Major issues 與目前 source。
2. 列出每一項：仍存在 / 已修正 / source 已重構需調整檔案路徑。
3. 跑 Plan v4 Task 0 baseline tests，記錄 exact pass/fail/error counts。
4. 若測試因 dependency/environment 無法 collection，明確列為 environment blocker；不要假裝 pass。
5. 不要修改 Design。

回報：

- Repository / Branch / HEAD
- Working tree 狀態
- Review v1 gap matrix
- Baseline tests executed/results
- Plan v4 是否可直接開始
- 若 Plan 與 source 路徑衝突，提出最小必要調整

此 preflight 完成後即可依同一份 Plan v4 繼續 implementation；不需要重新產生 Design。
```

# Codex Prompt — v4 Phase 0 Completion Implementation Contract

```text
請依 approved Design v3 + Implementation Review v1 + Plan v4 完成 Phase 0 剩餘工作：

docs/superpowers/specs/2026-09-02-sra-unified-api-security-boundary-design-v3.md
docs/superpowers/reviews/2026-09-02-sra-unified-api-security-boundary-implementation-review-v1.md
docs/superpowers/plans/2026-09-02-sra-unified-api-security-boundary-plan-v4.md

開始前先完整閱讀以上三份文件與 AGENTS.md、.codex/memory.md、.codex/backlog.md。

這是一份 execution contract：

1. 修改前先檢查目前 repository 的實際實作。
2. 記錄 Repository、Branch、HEAD commit；若沒有資訊，不可捏造。
3. 目前 source code 若已重構，實際程式狀態優先於 Plan 中舊的檔案路徑，但 security contract 不得因此被弱化。
4. 除非 Design v3 無法實作，否則不得自行重新設計架構。
5. 不得默默弱化 security、transaction、validation、audit、error handling、owner isolation、fail-closed behavior 或 secret handling。
6. 依 Plan v4 Task 0 → Task 7 執行；已在目前 source 完成的 step 先驗證，不重做。
7. 每個 behavior change 採 TDD：先有會失敗的 regression，再做最小修改，再跑 targeted tests。
8. 發現 Plan 與目前程式碼衝突時，先分析衝突，採最小必要調整，不自行擴張 scope。
9. 不要把舊 .codex/memory.md 的「305 passed」當作目前完成證據；source + tracked tests + 本次 fresh runs 才是證據。
10. 不要降低既有 Editor RBAC assertions 或 canonical api.* namespace guard。

本輪必須特別完成以下尚未收尾項目：

A. Security env/bootstrap consistency
- api.main 必須在 configuration-backed security/router globals 建立前完成 bootstrap_env()。
- api.security.cli 必須在建立 ServiceKeyStore 前 bootstrap env。
- .env 中的 SRA_SERVICE_KEYS_FILE 必須讓 API 與 CLI 指向同一 store。
- 修完後移除文件中「CLI 不會讀 .env」的 workaround 說法。

B. Authenticated-or-signed shared resolver
- 實作/使用共用 require_principal_or_capability（或目前 source 中等價且清楚命名的 helper）。
- invalid Authorization header 不得 fallback 到 sig。
- capability validation 必須在 resource lookup/serialization 前完成。
- docs detail/fulltext/export 不再各自維護會漂移的 ad hoc auth logic。

C. Canonical signed query contract
- duplicate sig / format / download / text_layer / session_id / turn_id fail closed。
- signed browser boolean 只接受 canonical 0/1。
- representation/resource/session/turn substitution fail closed。
- capability path 拒絕 unsupported/security-sensitive extra query keys。
- signed document detail/fulltext/Word 成功 response 加：
  Cache-Control: no-store
  Referrer-Policy: no-referrer
  X-Content-Type-Options: nosniff

D. Service-key correctness and audit
- expires_at 必須可安全 parse/normalize；malformed/naive value 不得讓 resolve 500。
- HTTP superuser create/list/revoke 與 CLI create/list/revoke 要有 tracked tests。
- corrupt store fail closed and preserve original。
- cross-process concurrent mutations 必須有 tracked test，不能只寫在 memory 說手動測過。
- audit：authn denied、authz denied、service-key create/revoke、admin cross-owner Job access。
- audit/log/API/CLI 不得出現 raw service key、token_digest、Authorization、user bearer、sig。

E. Report Job migration hardening
既有 ordering 不得改：

legacy version 0
→ validate supported legacy schema/constraints/index
→ create report_jobs_new
→ copy explicit columns with owner NULL
→ validate staged rows + required non-null
→ ALTER old report_jobs → report_jobs_old
→ ALTER report_jobs_new → report_jobs
→ only now CREATE partial owner-scoped unique index
→ validate canonical schema/index/rows and absence of old global uniqueness
→ DROP report_jobs_old
→ PRAGMA user_version=1
→ verify version=1
→ COMMIT

另外：
- fresh DB 直接 version 1 且需 canonical validation。
- already-version-1 reopen 也需 canonical validation，不能只信 user_version。
- failure injection 要在 migration SQL operation boundary，不只 post-step checkpoint。
- copy/rename/index/version failure 後 close + reopen 證明完整 rollback：legacy table/rows/global uniqueness/version0 保留，report_jobs_new/report_jobs_old 不殘留。
- concurrent initialize 要有 regression。

F. CORS / production secret
- reuse api.services.auth_support.PRODUCTION_ENVS，不另複製 production 定義。
- production empty CORS list != wildcard。
- wildcard development mode 不得搭配 credentialed '*'.
- configured origin preflight 要驗 Authorization、Content-Type、Idempotency-Key、既有 session headers。
- production missing/weak SRA_SIGNED_URL_SECRET 要 fail startup/config。
- non-production fallback 若保留，必須 warning 且不得印 secret。

G. Adversarial / least privilege tests
至少覆蓋：
- spoofed OpenWebUI/session headers 不構成 authentication。
- model:read 不能 invoke；model:invoke 不能 models list。
- OpenWebUI key 只有 model:read + model:invoke，不能 create Report Job。
- Batch key 不得 invoke chat unless explicitly scoped。
- service key 不能進 Editor users/service-key admin RBAC。
- Job IDOR 返回 404。
- invalid Authorization + valid sig 仍拒絕。
- signed capability cross-resource/cross-representation substitution 拒絕。
- SQL/path/query injection values 只能當 data 或被 validation 拒絕。
- revoke OpenWebUI key 後下一次 protected request → 401。

H. Docs / .codex
- 更新 README、security docs、report API/automation/operations examples，加 Authorization placeholder。
- 保留 SRA_SIGNED_URL_SECRET / SRA_SERVICE_KEYS_FILE / sra_sk_... 三者清楚區分。
- 更新 .codex memory/backlog 只能依本次 fresh verification，不可延用舊 completion claim。
- 不要把 runtime auth/audit/service-key files、.env.local、logs、cache 加入 commit。

測試要求：

1. 每 Task targeted tests。
2. Plan v4 Task 7 security/auth full targeted gate。
3. affected API/Job regression gate。
4. PYTHONPATH=. pytest tests -q --tb=short。
5. python -m compileall sra_api api tests。
6. git diff --check。
7. canonical namespace rg guard。
8. credential/digest/sig leak review。
9. git status / tracked runtime-secret review。
10. manual no-key/OpenWebUI-key/Batch-key/revoked-key/signed-link/production-secret smoke gate。

不要把 dependency collection error 算成 pass。
不要因為 full suite 很大就只跑 targeted tests後宣稱完成。
不要修改 unrelated Agent/retrieval/prompt behavior。

完成後必須回報：

- Repository
- Branch
- Baseline commit
- Design version: v3
- Plan version: v4
- Changed files
- Behavior changes
- Tests executed
- Test results (exact pass/fail/error counts)
- Deviations from Plan v4
- Remaining issues / risks

只有所有 required gate 實際完成且沒有 blocking/high security finding，才可以寫：
「Phase 0 v3 security gate passed after Plan v4 completion」
```

# Codex Prompt — v4 Post-Implementation Security Review

```text
請對 Plan v4 完成後的 repository 做 implementation security review，不要新增新功能，也不要重新設計 Design v3。

必讀：

docs/superpowers/specs/2026-09-02-sra-unified-api-security-boundary-design-v3.md
docs/superpowers/reviews/2026-09-02-sra-unified-api-security-boundary-implementation-review-v1.md
docs/superpowers/plans/2026-09-02-sra-unified-api-security-boundary-plan-v4.md

先記錄 actual Repository / Branch / HEAD。

逐項 adversarial review：

1. env bootstrap
   - .env 的 SRA_SERVICE_KEYS_FILE 是否在 API process-global store 建立前生效。
   - CLI 是否使用同一 bootstrap 規則。
   - 是否仍可能 API/CLI 讀不同 store。

2. credential authority
   - malformed/invalid/revoked/expired bearer → 401。
   - valid principal missing scope → 403。
   - invalid Authorization + valid sig 不可 fallback。
   - service key 不可通過 Editor RBAC。

3. signed capability
   - duplicate protected query keys fail closed。
   - unsupported/extra security-sensitive query fail closed。
   - detail/fulltext/session/turn/representation substitution fail closed。
   - signed response headers完整。
   - capability validation在 resource lookup前。

4. service-key persistence
   - raw key只顯示一次且不持久化。
   - digest不出現在 API/CLI/audit/log/error。
   - corrupted store preserve + fail closed。
   - concurrent processes無 lost update。
   - expires_at malformed/naive不造成500。

5. Report Job migration
   - legacy constraints/index validation完整。
   - fresh DB version1。
   - version1 reopen canonical validation。
   - migration ordering與 Design v3 完全一致。
   - partial owner index只在 rename後 canonical table 建立。
   - failure injection在 SQL operation boundary。
   - copy/rename/index/version failure reopen後仍完整 legacy state。
   - no report_jobs_new/report_jobs_old residue。
   - owner-scoped idempotency取代 global uniqueness。
   - unrelated principal Job IDOR → 404。

6. audit
   - authn denied / authz denied / key create/revoke / admin cross-owner access都有記錄。
   - audit不含 credential/sig/digest。

7. CORS/production
   - reuse PRODUCTION_ENVS。
   - production empty origins不是 wildcard。
   - wildcard不與 credentials '*'組合。
   - production missing/weak signing secret fail closed。

8. OpenWebUI least privilege
   - key只有 model:read + model:invoke。
   - models/chat可用。
   - Job create拒絕。
   - browser signed citation/Word不需要 service key。
   - revoke後下一次 request 401。

9. regression / hygiene
   - canonical api.* namespace guard乾淨。
   - runtime auth/audit/key/.env.local/cache/log檔沒有被誤 track。
   - report docs/examples已加 Authorization placeholder。
   - .codex memory/backlog與實際 tests一致。

必須 fresh 執行：
- Plan v4 Task 7 targeted security/auth gate
- affected API/Job regression gate
- full pytest suite
- compileall
- git diff --check
- namespace rg guard
- secret/digest/sig scan

回覆格式：

- Baseline Repository / Branch / Commit
- PASS / NOT PASS
- Blocking / Major / Minor / Improvement findings
- 每個 finding：位置、原因、實際結果、正確修法、是否需升版 Design/Plan
- Tests executed + exact results
- Deviations from Plan v4
- Remaining risks

如果問題只是 implementation，不要建立 Design v4。
只有 Design v3 本身出現 blocking architecture issue 或需求實質變更，才建議 Design 升版。

只有沒有 Blocking/Major security issue且所有 required tests fresh pass時，最後才寫：
「Phase 0 v3 security gate passed after Plan v4 completion」
```
