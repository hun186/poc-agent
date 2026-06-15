# 技術決策（Technical Decisions）

## Current Summary

- Reset token 以可複製 modal 呈現，不再使用 `alert`；保留 Clipboard API 與 textarea fallback。
- Editor 與 `portable_auth_pack` 維持靜態 HTML / CSS / vanilla JS 架構；主功能入口位於頂端 header，多層導航採桌機 hover、觸控 click 的漸進式互動。
- Editor 工作區由導航狀態切換；文件搜尋 / 編修顯示 ES editor，其餘帳號、審核、audit、統計頁採單欄呈現。
- 文件異動與帳號操作共用 audit 基礎資料，但以前端頁面與 `action_prefix` 分流；一般使用者僅能查自己的 `auth.*` 帳號操作紀錄。
- 共用 `audit_tools.js` 負責 audit chart、分頁與 progressive nav；主系統與 portable auth pack 需同步維護。
- Auth 採四層角色：`data_reader`、`data_editor`、`db_operator`、`superuser`；legacy `user` 正規化為 `data_editor`。
- Auth security 決策：不存在帳號仍做 dummy password hash timing balance；登入 / reset-password / register 採 process-local throttle；公開登入失敗與註冊回應避免帳號列舉；production 必須設定足夠強度 token secret。
- 長期記憶採 active summary + archive 濃縮模式；`.codex/archive/` 僅追溯時讀取。
- 可視 UI 變更若環境缺少 Playwright / browser runtime，採靜態 UI 測試與 JS 語法檢查替代，並於 known issues 記錄。

## Recent Changes

- 2026-06-14：主系統與 `portable_auth_pack` route / static JS 進行責任導向拆檔，但維持 API path 與既有 contract。
- 2026-06-14：註冊 API 對成功申請與 duplicate username 回相同泛用訊息，duplicate 只留內部 audit；註冊節流以 `client_host` 為 key。
- 2026-06-14：usage stats username 篩選改為 exact match 並支援逗號多選；非 superuser 仍強制限縮為自己。
- 2026-06-14：統計儀表板在個人模式隱藏使用者多選，改顯示 scope note 與 focus-stable tooltip。
- 2026-06-14：帳號操作 audit / usage stats 顯示與統計 `client_host`，讓帳號操作紀錄頁與儀表板可查來源 IP。

## Archived History

- `decisions.md-20260614-125305.md`：歸檔 2026-06-14 前完整 technical decisions，包含 reset token modal、導航架構、工作區切換、共用 audit tools、Auth security、長期記憶濃縮、角色層級與近期拆檔 / 註冊安全決策。

## 2026-06-15 Report Agent 拆檔決策

- 當 Python orchestration 檔案主要因大型 prompt 或純 helper 過長時，優先拆成同 package 的小模組，避免改動既有 public import path 與 runtime behavior。
- `ReportAgent` 與 `ask_with_report()` 的外部入口維持在 `agent/report_agent.py`，降低呼叫端遷移成本；prompt / config / stats helper 則使用相對 import 管理。

## 2026-06-15 Agent Router 拆檔決策

- 當 orchestration 檔案同時包含大型 prompt、分類 helper 與 session / dispatch 流程時，優先將 prompt + router helper 拆到同 package 小模組，讓主入口維持薄 orchestration。
- `answer_with_routing()` 的外部入口維持在 `agent/agent.py`；router 相關 public helper 則以 `agent/routing.py` 作為後續維護位置，並於必要時在 `agent.agent` 保留 re-export 相容。

## 2026-06-15 Auth Store 拆檔決策

- 對正在使用且超過 600 行的 auth store，優先依責任拆出 support / token 小模組，而不是改變 route 或 storage contract。
- 為降低呼叫端遷移風險，`api.services.auth_store` 與 `portable_auth_pack.fastapi_auth_pack.auth_store` 保留原本 public symbols；新模組只承接內部 helper 與 token 實作。
