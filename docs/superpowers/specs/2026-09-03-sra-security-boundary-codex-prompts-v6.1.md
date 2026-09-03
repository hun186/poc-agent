# SRA Unified API Security Boundary — Codex Prompts v6.1

## Codex Prompt — v6.1 Final Repository Completion + Real ES E2E Contract

```text
你是 implementation agent。請依 actual repository 執行 SRA Unified API Security Boundary Phase 0 的最後 completion delta。

這是 execution contract，不是重新設計產品或架構。

必讀，依下列優先順序：
1. AGENTS.md
2. docs/superpowers/specs/2026-09-02-sra-unified-api-security-boundary-design-v3.md
3. docs/superpowers/reviews/2026-09-03-sra-unified-api-security-boundary-implementation-review-v3.md
4. docs/superpowers/plans/2026-09-03-sra-unified-api-security-boundary-plan-v6.1.md
5. actual source code / tests

Review v2 若 repository 內缺失，不得因此停止 implementation。Review v3 是本輪 authoritative review；Review v2 只需作歷史 traceability 補回，不是 execution prerequisite。

Baseline / execution rules：

1. 修改前先記錄 actual Repository、Branch、HEAD commit、git status；沒有 remote 就不要捏造 repository URL。
2. actual source code 是 implementation baseline。若 Plan 中路徑已重構，以 source 為準，但不得弱化 Design v3。
3. Design v3 維持 authoritative。不要建立 Design v4，除非 actual source 證明 Design v3 本身存在 blocking architecture contradiction。
4. Plan v6.1 只處理 Review v3 的剩餘 completion delta。不要重做已完成的 env bootstrap、Service Key store、signed capability validation、CORS hardening、Report Job migration/concurrency、既有 audit 或 security headers。
5. 不得弱化 authentication、authorization、scope、owner isolation、404 concealment、transaction、rollback、validation、audit、fail-closed、secret handling 或 Editor RBAC。
6. production behavior change 必須先有 failing regression，確認 RED，再做最小修正，再確認 GREEN。
7. Plan/source 衝突先分析，採最小必要調整；不要自行擴張 scope。
8. dependency/collection/import failure 不得算 pass。
9. 不得在 output、commit、docs、audit、log 中重述 raw Service Key、Authorization header、token_digest 或 capability signature。
10. 完成後必須回報 changed files、behavior changes、tests、exact results、deviations、remaining risks。

本輪只做以下 repository completion 工作：

A. Restore traceability
- 確保 Review v3 位於：
  docs/superpowers/reviews/2026-09-03-sra-unified-api-security-boundary-implementation-review-v3.md
- Review v2 若缺失，補回歷史原文：
  docs/superpowers/reviews/2026-09-02-sra-unified-api-security-boundary-implementation-review-v2.md
- 不要重寫 Review v2 來符合現在 source。

B. Fix direct-principal signed-resource authorization-denied audit
目前 Review v3 指出：`require_principal_or_capability()` 對合法 principal 但缺 required_scope 時直接 403，沒有 `security.authorization_denied` audit。

要求：
- 先新增 regression，證明目前 403 但 audit 缺失。
- 在 authenticated principal insufficient-scope path 使用既有安全 audit helper。
- event 至少包含：action=`security.authorization_denied`、reason=`insufficient_scope`、principal_kind、subject、required_scopes。
- 仍回 403。
- 不改 invalid Authorization precedence，也不允許 fallback signed capability。

C. Fix Report Job owner-mismatch authorization audit
目前 status/download 對 existing Job + 正確 read/download scope + owner 不符時，外部 404 concealment 正確，但沒有 authorization-denied audit。

要求：
- 先新增 status 與 download regression。
- Job 不存在：仍 404；不得假造 owner-mismatch audit。
- Job 存在但 owner/admin authorization 失敗：寫安全 audit，action=`security.authorization_denied`、reason=`job_owner_mismatch`，含 principal kind/subject、job_id、operation=read/download。
- 對外仍必須 404，不能改成 403，避免洩漏 Job existence。
- 成功的 admin cross-owner access audit維持原行為。

D. Replace helper-only non-superuser Service Key test with actual HTTP route regression
現在的 `test_non_superuser_cannot_administer_service_keys` 只直接呼叫 RBAC dependency，不足以證明 route wiring。

要求：
- 用 FastAPI TestClient 真正打 `/v1/auth/service-keys` create/list/revoke。
- 透過 canonical Editor auth dependency seam，把 `current_user` override 成有效 `data_reader` 或其他非 superuser。
- 三個 HTTP operations 都必須 403。
- 驗證既有 RBAC denied audit不含 credential。
- 如果 real HTTP test 已 pass，不要為風格改 production route。

E. Complete signed Word security-header regression
在既有 signed Word successful download test 明確 assert：
- Cache-Control: no-store
- Referrer-Policy: no-referrer
- X-Content-Type-Options: nosniff

如果 production 已正確回 header，只補 test，不重構 export route。

F. Resolve startup signing-secret audit item without adding fragile startup dependencies
- production missing/weak SRA_SIGNED_URL_SECRET 的 RuntimeError fail-closed 行為保持不變。
- 不要為了 pre-start audit 強迫初始化 application audit store。
- 在 `.codex/decisions.md` 記錄：這種 application startup validation failure 以 raised startup exception + service/process logs 作為 pre-request authoritative audit channel。
- 不得 log secret 值。

G. Fresh repository gate
至少執行 Plan v6.1 Task 5 指定 targeted Phase 0 suite、affected tests、full pytest、compileall、git diff --check、namespace guard、secret/runtime-artifact scans。
- 必須回報 exact pass/fail/error/warning counts。
- 不得引用舊的 343 pass 當這輪 fresh evidence。

最重要的 live acceptance sequencing：

1. Fast security regression 可 mock downstream Agent seam。
這些測試只證明 authn/authz/scope/RBAC boundary，不代表 Agent/ES E2E。

2. Phase 0 final deployment acceptance 必須真的跑：
Service Key
→ /v1/chat/completions
→ Router 選到 report/analysis 長時間 Agent
→ 真正 Elasticsearch retrieval
→ 真實 source/evidence
→ 長時間 Agent 綜整
→ final report
→ word_export.url
→ signed URL GET
→ 真實 DOCX

不得 mock Elasticsearch、不得 mock Agent、不得用假 report response 宣稱 final deployment PASS。

3. 現有 working acceptance Service Keys 在 real E2E 完成前不得變更：
- 不得 revoke
- 不得 rotate
- 不得 replace
- 不得 delete
- 不得先做 hygiene cleanup 破壞 live harness

但同時：
- 不得把 raw key 複製到任何新的 source/docs/test/log/audit/report/commit。
- 不得 print raw key。
- execution report 不得重述 raw `sra_sk_...`。

4. Real E2E timeout：
- connection timeout可約 10 秒。
- long read timeout可設定 1800 秒；真實 workload 必要時可到 3600 秒。
- timeout 不能誤報成 401/403 security failure。
- auth boundary通過但 long Agent timeout，只能分開記 auth pass；deployment E2E仍是 FAIL/NOT COMPLETED。

5. Real E2E 不只看 HTTP 200，必須有 evidence：
- route 真正是 report/analysis Agent，不是 PURE_LLM/background short answer
- 真正查 Elasticsearch
- 有 retrieved source/evidence
- retrieval後 Agent/report pipeline 繼續執行
- final report非空
- word_export URL存在
- signed Word GET 不帶 Authorization
- HTTP 200
- DOCX MIME/ZIP結構有效且可開啟/解析

6. 如果 Codex environment 無法連到 private deployment / ES：
- Fast live smoke與 Real long Agent E2E 明確標記 NOT EXECUTED。
- 不得把 proxy 403 當 SRA security failure。
- 不得因此先 revoke/rotate current working acceptance credentials。
- repository implementation可以完成並 commit，但 deployment acceptance保持 pending。

7. Post-E2E credential hygiene 只有在 real E2E PASS 後才做：
- 建 replacement key
- replacement fast smoke pass
- revoke old exposed key
- old key下一次 protected request 401
- smoke harness再改成 environment/ignored local config
- replacement raw key不得進 Git

如果 E2E NOT EXECUTED/FAIL，就保留 working acceptance credentials並列 pending。

完成後固定回報：

- Repository
- Branch
- Baseline commit
- Resulting commit (if committed)
- Design version: v3
- Authoritative Review: v3
- Plan version: v6.1
- Changed files
- Behavior changes
- Tests executed
- Exact pass/fail/error/warning counts
- Fast live security smoke: PASS / FAIL / NOT EXECUTED
- Real long Agent E2E: PASS / FAIL / NOT EXECUTED
- Evidence that Elasticsearch retrieval actually occurred
- Evidence that report/analysis Agent path actually executed
- Word export/download result
- Credential handling: preserved pending E2E / rotated after E2E
- Deviations from Plan v6.1
- Remaining issues / risks

只有 repository automated gates fresh pass、Review v3 的 Major repository issues全部消除、沒有新 Blocking/Major security finding，而且 real ES + long Agent + signed Word E2E真的 PASS，才可寫：

「Phase 0 v3 repository security gate passed after Plan v6.1 completion.」
「Phase 0 v3 deployment acceptance passed with real Elasticsearch retrieval, long-running report Agent execution, and signed Word export.」

如果 repository gate完成但 real E2E無法在 Codex environment執行，請寫：

「Phase 0 v3 repository security gate passed after Plan v6.1 completion, but deployment acceptance remains pending because the real Elasticsearch/long-Agent/Word E2E was NOT EXECUTED. Existing working acceptance credentials were intentionally left unchanged.」
```

## Codex Prompt — v6.1 Post-Implementation Self-Review

```text
請只對 Plan v6.1 實作後的 actual repository 做 Phase 0 self-review，不新增功能、不重新設計 Design v3。

必讀：
- AGENTS.md
- docs/superpowers/specs/2026-09-02-sra-unified-api-security-boundary-design-v3.md
- docs/superpowers/reviews/2026-09-03-sra-unified-api-security-boundary-implementation-review-v3.md
- docs/superpowers/plans/2026-09-03-sra-unified-api-security-boundary-plan-v6.1.md

Review v2 只作歷史 traceability，不是本輪 authoritative requirement source。

先記錄 Repository / Branch / HEAD / git status。

逐項確認：
1. direct-principal signed-resource insufficient scope是否 403 + security.authorization_denied audit。
2. existing cross-owner Report Job status/download是否仍404 concealment，同時內部有 authorization_denied owner-mismatch audit。
3. nonexistent Job是否仍404且不假造 owner-mismatch event。
4. non-superuser Service Key administration是否透過 actual HTTP create/list/revoke route測到403，而非只測 helper。
5. signed Word成功 response是否明確測 no-store/no-referrer/nosniff。
6. startup signing-secret fail-closed是否保持，且 startup audit channel disposition已記錄、不洩漏 secret。
7. Review v3 artifact是否存在；Review v2若補回是否保持歷史原文。
8. targeted/full pytest與static/security scans是否 fresh pass。
9. 是否新增任何 raw Service Key / Authorization / token_digest洩漏。
10. real ES → long Agent → signed Word E2E是否真的執行；若沒有，必須是 NOT EXECUTED。
11. real E2E之前是否保持 existing working acceptance credentials不變。

回覆：
- PASS / NOT PASS
- Blocking / Major / Minor / Improvement
- 每個 finding的位置、原因、可能結果、正確修法、Design/Plan是否需升版
- fresh test exact counts
- Real E2E status與證據
- Word artifact結果
- credential sequencing結果
- remaining risks

只有 Design v3 本身發現 blocking architecture contradiction或需求實質變更才建議 Design v4；純 implementation/test/acceptance 問題不得升版 Design。
```
