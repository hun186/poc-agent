# Codex Prompt — v2 Re-Review Before Implementation

```text
請先不要修改程式碼。

前一次 review 已指出 Phase 0 計劃的阻斷問題。現在請重新審查 v2：

docs/superpowers/specs/2026-09-02-sra-unified-api-security-boundary-design-v2.md
docs/superpowers/plans/2026-09-02-sra-unified-api-security-boundary-plan-v2.md

請確認 v2 已完整解決：

1. canonical runtime namespace 固定為 api.*；不得再讓同一個 stateful module 以 api.* 與 sra_api.* 形成雙 singleton。
2. editor_dependencies 不再 capture AUTH_STORE by value，並修復 standalone/combined auth baseline。
3. Job owner/idempotency migration 明確採 BEGIN IMMEDIATE + transactional table rebuild + partial owner-scoped unique index + rollback test。
4. service-key JSON store 具 process RLock + OS-level cross-process lock，鎖住完整 read-modify-write；corrupt store fail closed。
5. service-key raw key 不落盤；digest只存在受保護 persistence/recovery file，不得出現在 API list/log/audit/exception/repr。
6. optional_principal + require_principal_or_capability 的 fail-closed contract完整：
   - 無 Authorization 才可 fallback signed capability
   - invalid Authorization + valid sig 仍拒絕
7. signed URL 使用單一 sig，並精確 bind：
   - doc_detail
   - doc_fulltext + format/download/text_layer
   - legacy_word + session_id + exact turn_id
   並拒絕 duplicate/tampered protected query。
8. browser-facing Word signed URL 不允許 implicit latest turn。
9. production 判定重用既有 PRODUCTION_ENVS={"prod","production"}，production signing secret 缺失/過短 fail startup。
10. /docs、/openapi.json、/redoc 與 /v1/docs/* 已有不混淆的明確政策。
11. signed fulltext capability 無法取得完整 ES _source detail；doc detail 完整 _source 是 Phase 0 明確保留的既有 contract。
12. reverse proxy/access log 對 sig query leakage 已被納入 operations/security docs。
13. SQL injection、IDOR、path traversal、scope escalation、secret leak negative tests足夠。

另外請重新跑：
- auth role-options test standalone
- auth + security-boundary combined baseline

若目前 baseline failure 的根因與 v2 Task 0 假設不同，請指出實際 root cause，不要為了讓 test pass 去降低 RBAC assertion。

只回覆：
- v2 是否仍有 blocking issue
- Task 0 root-cause 判斷
- 需要再調整的檔案/contract
- exact baseline test結果

若無阻斷，最後明確寫：
「可依 Phase 0 v2 計劃實作」

此階段不要修改 code。
```

# Codex Prompt — v2 Implementation

```text
請依 approved v2 文件實作 Phase 0：

docs/superpowers/specs/2026-09-02-sra-unified-api-security-boundary-design-v2.md
docs/superpowers/plans/2026-09-02-sra-unified-api-security-boundary-plan-v2.md

先依 AGENTS.md 載入 .codex 專案記憶。

重要：Task 0 是 blocking prerequisite。
在新增 service key / signed URL 之前，先修復並驗證現有 Editor auth module/singleton baseline。

不可跳過的 contract：

A. Import / Editor auth
- canonical stateful runtime namespace = api.*
- 新 security files實體放 sra_api/security，但 runtime import = api.security.*
- 禁止 api.services.auth_store 與 sra_api.services.auth_store 雙載入形成兩個 AUTH_STORE
- editor_dependencies 不得 capture AUTH_STORE by value
- standalone + combined Editor auth baseline 必須全綠

B. Service key
- >=256-bit random
- sra_sk_* format
- raw secret只在 create時顯示一次
- SHA-256 digest可存在 owner-only persistence/recovery file
- raw/digest不得出現在 list/log/audit/exception/repr
- RLock + OS-level cross-process lock鎖住完整 read-modify-write
- corrupt store fail closed且不得覆蓋原檔
- service key不可進 Editor user-only API

C. Unified principal
- current_principal
- optional_principal
- require_scopes
- require_principal_or_capability
- invalid Authorization + valid sig 不可 fallback

D. Protected routes
- GET /v1/models → model:read
- POST /v1/chat/completions → model:invoke
- POST /v1/report/word → report:sync
- Job create/read/download → scopes + owner
- docs/export → authenticated direct scope OR exact signed capability

E. Job migration
- mandatory BEGIN IMMEDIATE table rebuild
- owner_kind/owner_id
- legacy owner NULL, admin-only
- partial UNIQUE(owner_kind, owner_id, idempotency_key) WHERE key IS NOT NULL
- rollback test
- authorization在任何 _view/metadata/artifact detail前完成
- cross-owner → 404
- SQL全面 parameterized

F. Signed capability
- one query parameter: sig
- doc_detail binds exact doc_id
- doc_fulltext binds doc_id + format + canonical download 0|1 + text_layer
- legacy_word binds session_id + exact turn_id
- browser signed Word不可使用 latest-turn implicit behavior
- reject duplicate sig/protected params、tampering、representation substitution
- no credentials inside URL
- signed response: Cache-Control no-store + Referrer-Policy no-referrer + nosniff
- query sig 不可寫入 application debug log
- operations docs說明 reverse-proxy query logging leakage

G. Environment / docs
- production semantics重用既有 PRODUCTION_ENVS
- production缺/弱 SRA_SIGNED_URL_SECRET → startup fail
- /openapi.json public
- /docs public
- /redoc disabled unless existing dependency is demonstrated
- /v1/docs/* 是 protected resource，不可與 Swagger /docs 混淆

H. OpenWebUI
- admin只設定一把 OpenWebUI service key
- scopes只有 model:read + model:invoke
- end users不用設定/知道 key
- Batch Scheduler未來使用另一把 key

不要擴充 Batch Scheduler、Windows GUI、Server Dashboard、OAuth/OIDC、Redis/Celery/PostgreSQL。

採 TDD task-by-task。
每個 blocking/security task測試後再進下一個。

完成後執行：
1. plan全部 targeted tests
2. affected API regression tests
3. `PYTHONPATH=. pytest tests -q --tb=short`
4. `python -m compileall sra_api`
5. `git diff --check`
6. canonical namespace guard
7. credential/sig leak review
8. service-key concurrent process mutation test
9. Job migration rollback test
10. manual no-key/OpenWebUI-key/Batch-key/revoked-key/signed-link smoke tests

最後回報 exact pass/fail counts；未執行的測試不得宣稱成功。
```

# Codex Prompt — v2 Post-Implementation Security Review

```text
請不要新增 Batch/GUI 功能。

針對 Phase 0 v2 做 adversarial security review，並實際嘗試下列 bypass：

1. 無 Authorization 直接 models/chat/report/job。
2. spoof X-OpenWebUI-*、X-Session-Id、Origin/CORS。
3. 同一 stateful auth/security module 是否仍可雙 namespace載入造成第二 singleton。
4. service key scope escalation與 Editor admin誤用。
5. revoked/expired key。
6. concurrent CLI/API service-key create/revoke lost update。
7. corrupt service-key store是否會被空 store覆寫。
8. Job cross-owner IDOR、legacy unowned policy、owner-scoped idempotency。
9. Job migration rollback與既有 rows完整性。
10. signed detail/fulltext capability substitution。
11. format/download/text_layer query tampering、duplicate sig、duplicate protected params。
12. signed Word session/turn substitution與 implicit latest-turn bypass。
13. invalid Authorization + valid sig fallback bypass。
14. raw service key / digest / Authorization / sig 是否出現在 response/log/audit/exception/repr。
15. SQL injection、dynamic SQL、path traversal。
16. /docs vs /v1/docs policy是否正確。
17. production signing secret fail-open。
18. access log / reverse proxy是否可能記錄 sig query，文件是否明確警示。

回覆：
- Critical / High / Medium / Low findings
- reproducible steps
- affected endpoints/files
- fixes
- exact tests run/results

若沒有 blocking/high finding，最後明確寫：
「Phase 0 v2 security gate passed」
```
