# SRA Security Boundary Codex Prompts — v6

## Which prompt to use now

Use **`Codex Prompt — v6 Phase 0 Final Completion + Real ES E2E Contract`** for the next Codex implementation run.

This prompt supersedes the remaining-work instructions in v5. Design v3 remains authoritative.

---

# Codex Prompt — v6 Phase 0 Final Completion + Real ES E2E Contract

```text
請以目前 actual repository 為 baseline，依 Design v3 完成 Phase 0 最後 security/acceptance 工作。

必讀：

AGENTS.md
.codex/memory.md
.codex/backlog.md
docs/superpowers/specs/2026-09-02-sra-unified-api-security-boundary-design-v3.md
docs/superpowers/reviews/2026-09-02-sra-unified-api-security-boundary-implementation-review-v2.md
docs/superpowers/plans/2026-09-03-sra-unified-api-security-boundary-plan-v6.md

這是 implementation execution contract，不是重新設計需求。

Baseline / execution rules：

1. 開始前記錄 actual Repository、Branch、HEAD commit、git status；沒有 remote 就不要捏造 repository URL。
2. actual source code 是 implementation baseline；若 Plan 路徑已重構，以 source 為準，但不得弱化 Design v3。
3. Design v3 維持 authoritative。本輪不要建立 Design v4，除非 actual source 證明 Design v3 本身有 blocking architecture contradiction。
4. Plan v6 是 v4/v5 的 completion/acceptance delta。不要重做已完成的 env bootstrap、shared capability resolver、signed response headers、Service Key expiration validation、Report Job migration hardening、PRODUCTION_ENVS reuse。
5. 不得弱化 authentication、authorization、scope、owner isolation、transaction、rollback、validation、audit、fail-closed、secret handling、Editor RBAC。
6. 不擴張到 Batch Scheduler、GUI/Dashboard、Redis/Celery/PostgreSQL、OIDC/OAuth、rate limiting 或 unrelated Agent/retrieval redesign。
7. production behavior change 先建立 failing regression，再做最小修正，再跑 targeted tests。
8. Plan/source 衝突先分析，採最小必要調整，不自行重新定義 architecture。
9. dependency/collection error 不得算 pass。
10. 完成後回報 exact changed files、behavior、tests、counts、deviations、risks。

最重要的 acceptance 規則：

A. Fast security regression 與 final E2E 是兩種不同測試
- authn/authz/scope/RBAC 的快速 regression 可以 mock downstream Agent seam，目的只是讓 401/403/200 deterministic、快速、可定位。
- 但 mock 測試絕對不能取代 Phase 0 final deployment acceptance。

B. Phase 0 final deployment acceptance 必須真的走完整產品鏈
必須實際驗證：

Service Key
→ /v1/chat/completions
→ router 選到 report/analysis 長時間 Agent
→ 真正查 Elasticsearch
→ 取得真實 source/evidence
→ 長時間 Agent 綜整
→ final report
→ word_export.url
→ signed URL GET
→ 真實 DOCX

不得 mock Elasticsearch、不得 mock Agent、不得用假的 report response 來宣稱 final acceptance PASS。

C. 現有 working smoke/E2E Service Keys 在 real E2E 完成前不得變更
- 不得 revoke
- 不得 rotate
- 不得 replace
- 不得 delete
- 不得因為 hygiene 要求就先改成另一組 credential
- 不得改壞目前可運作的 live smoke harness

這些 key 是 operator 目前用來完成 real E2E 的 acceptance credentials。
在 real E2E 完成以前先保留它們。

但：
- 不得把 key 值複製到新的檔案、測試、docs、.codex、commit message、audit、log 或 execution report。
- 不得 print credential。
- 不要在回報中重述任何 raw `sra_sk_...`。

D. credential hygiene 改到 real E2E PASS 之後
只有 real ES + long Agent + Word E2E 已實際 PASS 後，才進行：
- operator revoke/rotate 已暴露測試 key
- smoke harness 改讀 environment/ignored local config
- repository real-looking Service Key literal guard
- 舊 key 下一次 protected request → 401
- 新 replacement key fast smoke仍通過

如果 real E2E 尚未執行或失敗，不得提前做上述 key rotation/cleanup。

本輪 implementation 要完成：

1. Unified security audit + HTTP Service Key admin coverage
Tracked tests/behavior至少包含：
- authentication denied audit
- authorization denied audit
- service-key created audit
- service-key revoked audit
- admin cross-owner Report Job access audit
- superuser HTTP create/list/revoke
- non-superuser admin → 403
- service-key principal不能通過 Editor superuser dependency
- unknown scope validation failure
- revoked key下一次 protected request → 401
- raw key只允許出現在 create response；list/revoke/audit/log不能有 raw key/token_digest

2. Concurrency regressions
- cross-process Service Key mutation，同 store不得 lost update、JSON不得損壞、key_id唯一、不得persist raw key
- concurrent ReportJobStore initialize：fresh DB與supported legacy v0 DB都必須 canonical
- 不得殘留 report_jobs_new/report_jobs_old
- 若現有 locking/transaction 已 pass，不要為風格重構 production code

3. Signed capability adversarial regressions
- duplicate sig/format/download/text_layer/session_id/turn_id fail closed
- unsupported extra query key fail closed
- signed download只接受 canonical 0/1
- invalid Authorization + valid sig → 401，不 fallback capability
- cross-doc/resource/representation substitution reject
- legacy Word session/turn substitution reject
- capability validation before resource lookup
- signed detail/fulltext/Word success headers：no-store/no-referrer/nosniff

4. Fast OpenWebUI/scope matrix
這組可以 mock downstream Agent：
- no key models 401
- invalid key models 401
- model:read models 200
- model:invoke-only models 403
- model:read-only chat 403
- OpenWebUI model:read+model:invoke 通過 models/chat security boundary
- OpenWebUI key不能 POST report jobs
- report/batch key沒有 model:invoke不能 chat
- service key不能進 Editor admin
- spoofed X-OpenWebUI-Chat-Id/X-Session-Id 不構成 authentication
- revoked key下一次 protected request 401

注意：chat success-side 可 monkeypatch `execute_agent_turn` 或 current equivalent，只能宣稱 scope boundary pass，不能宣稱 Agent/ES/report E2E pass。

5. Startup/CORS
- production missing/weak SRA_SIGNED_URL_SECRET fail closed
- valid >=32-byte secret pass
- non-production fallback warning一次且不含 secret
- production empty CORS不 wildcard
- configured preflight允許 Authorization、Content-Type、Idempotency-Key、X-OpenWebUI-Chat-Id、X-Conversation-Id、X-Session-Id

6. Automated repository pre-E2E gate
fresh run：
- Phase 0 targeted suites
- affected API/Job regressions
- `PYTHONPATH=. pytest tests -q --tb=short`
- compileall
- git diff --check
- canonical namespace guard
- Authorization/token_digest/audit leak scan
- tracked runtime-secret/cache scan

在 real E2E 之前，不要因為目前 acceptance harness 仍持有原 working test key 就先修改/撤銷它。
但 implementation 不得新增 raw key 的其他副本。

7. Mandatory real live E2E — 不可用 mock 取代
如果 Codex environment 可連到 configured running SRA API/ES 並取得 operator test credentials，就執行；若做不到，標示 NOT EXECUTED，不能假裝 pass。

先跑 fast live matrix：
- healthz no key → 200
- models no key → 401
- models invalid → 401
- models read-only → 200
- chat read-only → 403
- report jobs OpenWebUI key → 403

接著跑真正 long report prompt。
read timeout 必須可設定，例如 1800 秒；若真實 workload 需要，可用 3600 秒。

Long E2E 必須證明，不只是 HTTP 200：
- route 真正選到 report/analysis Agent，而不是背景 LLM 直接短答
- 真正執行 Elasticsearch retrieval
- ES retrieval 有取得 source/evidence
- Agent/report pipeline 在 retrieval 後繼續執行
- final report content非空
- `choices[0].message.context.word_export.url` 存在（若 actual API contract路徑不同，以 current source 為準）
- GET signed Word URL時不帶 Authorization
- Word download HTTP 200
- Content-Type/DOCX ZIP結構有效
- 實際輸出檔非空且可開啟/解析

若 current implementation 有 route/context/source metadata，直接 assert。
若只能從 existing server/Agent/ES logs 證明真的查 ES與走 report Agent，記錄具體 evidence。
不要只因 response 200 就判 E2E pass。

Long read timeout：
- 若 auth boundary已通過但 1800/3600 秒內未完成，auth可分開記錄 pass；
- deployment E2E 必須記 FAIL/NOT COMPLETED，不能宣稱 pass；
- 不得把 timeout 誤報為 401/403 security failure。

8. Post-E2E credential hygiene
只有第7項 real E2E真正 PASS 後才執行：
- operator rotate/revoke已暴露的 acceptance test keys
- smoke harness改用 environment/ignored local config
- replacement key不得進 Git
- 加入/啟用 real-looking `sra_sk_...` literal guard
- old key protected request → 401
- replacement key fast live smoke pass

如果第7項 NOT EXECUTED/FAIL，就保留現在 working test credentials，明確列 pending，不能先改。

9. Final gates
real E2E + post-E2E hygiene完成後，再 fresh 跑：
- targeted Phase 0 suite
- affected suite
- full pytest
- compileall
- git diff --check
- namespace guard
- Authorization/raw key/token_digest leak scan
- real-looking service-key literal scan
- tracked runtime-secret/cache scan
- git status

完成後固定回報：

- Repository
- Branch
- Baseline commit
- Resulting commit (if committed)
- Design version: v3
- Review version: v2
- Plan version: v6
- Changed files
- Behavior changes
- Tests executed
- Exact pass/fail/error/warning counts
- Fast live security smoke result
- Real long Agent E2E: PASS / FAIL / NOT EXECUTED
- Evidence that Elasticsearch retrieval actually occurred
- Evidence that report/analysis Agent path actually executed
- Word export/download result
- Credential handling: preserved pending E2E / rotated after E2E
- Deviations from Plan v6
- Remaining issues / risks

只有 repository automated gates fresh pass、沒有 Blocking/Major security finding，而且 real ES + long Agent + signed Word E2E也真的 PASS，才可寫：

「Phase 0 v3 repository security gate passed after Plan v6 completion.」
「Phase 0 v3 deployment acceptance smoke passed with real Elasticsearch retrieval, long-running report Agent execution, and signed Word export.」

若 Codex environment 無法跑 real E2E，必須寫：

「Repository implementation verification completed to the extent available, but Phase 0 deployment acceptance remains pending because the real Elasticsearch/long-Agent/Word E2E was NOT EXECUTED. Existing working acceptance credentials were intentionally left unchanged.」
```

---

# Codex Prompt — v6 Post-Implementation Review

```text
請對 Plan v6 實作後的 actual repository 做 Phase 0 implementation + acceptance review，不新增功能，不重新設計 Design v3。

必讀：
AGENTS.md
docs/superpowers/specs/2026-09-02-sra-unified-api-security-boundary-design-v3.md
docs/superpowers/reviews/2026-09-02-sra-unified-api-security-boundary-implementation-review-v2.md
docs/superpowers/plans/2026-09-03-sra-unified-api-security-boundary-plan-v6.md

先記錄 Repository / Branch / HEAD / git status。

Review 必須分開判斷：

A. Repository security implementation
- unified audit
- HTTP Service Key admin/RBAC
- concurrency
- signed capability adversarial behavior
- OpenWebUI least privilege
- startup/CORS
- v4 migration/env/capability hardening沒有退化
- automated tests/static guards fresh結果

B. Real deployment E2E
不能只看 unit/mock tests。確認是否真的有 evidence：
- real Service Key request
- report/analysis Agent route
- actual Elasticsearch retrieval
- actual retrieved source/evidence
- long Agent completion
- final report
- word_export
- signed DOCX download

如果 B 沒有真的執行，結果必須是 NOT EXECUTED，不可用 mock coverage推論 PASS。

C. Credential sequencing
- 在 real E2E PASS 前，現有 working acceptance keys是否保持不變
- 有沒有把 raw key複製到新的 source/docs/log/audit/report
- 只有 E2E PASS 後才允許 rotate/revoke並改成 env/ignored config
- E2E未完成時不得因 hygiene 先破壞 live harness

回覆格式：
- Baseline Repository / Branch / Commit
- PASS / NOT PASS
- Blocking / Major / Minor / Improvement findings
- 每個 finding：位置、原因、實際/可能結果、正確修法、是否需升版 Design/Plan
- Tests executed + exact counts
- Real ES E2E result
- Evidence of ES retrieval
- Evidence of report Agent routing/execution
- Word artifact result
- Credential sequencing result
- Deviations from Plan v6
- Remaining risks

只有 Design v3 本身有 blocking architecture contradiction或需求實質變更才建議 Design v4；純 implementation/test/acceptance 問題只更新 Plan/Prompt。
```
