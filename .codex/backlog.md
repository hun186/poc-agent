# 待辦事項（Backlog）

## 高優先度

- 

## 中優先度

- 

## 低優先度

- 

## 技術債

- 

## 未來構想

- 

## 2026-06-11 後續改善建議

- 將 reset token modal 與 copy helper 抽成可重用小元件，避免 editor 與 portable auth pack 長期分岔。
- 修正 `data_ingestion/excel_to_sql/file_ops.py` 的 `datetime.utcnow()` deprecation warnings，改用 timezone-aware datetime。

---

---

## 2026-06-11 標題列導航後續改善建議

- 將 Editor 與 portable auth pack 的多層導航資料結構抽成可重用設定，降低兩份靜態 HTML 長期分岔風險。
- 在具備 Playwright / browser runtime 的環境補上標題列多層導航截圖或互動式 E2E 測試。


---

## 2026-06-11 Editor 導航與稽核後續改善建議

- 若 audit log 筆數成長，為 `GET /v1/editor/audit-logs` 增加 `action_prefix` 或 `category` query 參數，讓文件異動與帳號操作分流改由後端完成。
- 在具備 Playwright / browser runtime 的環境補上 Editor 單欄工作區與帳號操作紀錄頁的互動式截圖或 E2E 測試。

---

## 2026-06-11 共用 audit tools 後續改善建議

- 建立正式 static assets 掛載或簡易同步腳本，確保 `api/static/audit_tools.js` 與 `portable_auth_pack/static/audit_tools.js` 不會長期分岔。
- 在具備 Playwright / browser runtime 的環境補上桌機 hover navigation、觸控 click navigation、Editor 使用統計曲線與 portable auth pack 帳號統計曲線的 E2E 測試。
- 若 usage stats 篩選需求持續擴充，可加入 action 多選、使用者多選與匯出功能。

---

## 2026-06-12 Auth 資安後續改善建議

- 多 worker / 多 instance 部署時，將目前 process-local auth throttle 改為 Redis、database、API gateway 或 WAF 層級的共享 rate limiting。
- 為 superuser 加入 MFA 或高風險操作 re-authentication，例如發 reset token、直接重設密碼、刪除帳號。
- 補強前端 token 儲存安全性：評估 CSP、XSS hardening，或改用 HttpOnly Secure SameSite cookie 並同步設計 CSRF 防護。

## 2026-06-14 Auth 註冊安全後續改善

- 多 worker / 多 instance 部署時，將註冊 per-IP 節流與既有 login / reset-password throttle 一併改為集中式 Redis、database、API gateway 或 WAF rate limiting。
- 評估是否對註冊加入 CAPTCHA、email / help desk 驗證或管理員邀請碼，以進一步降低自動化濫用。

## 2026-06-15 Excel 匯入後續改善建議

- 若使用者仍常遇到 `imported_with_errors`，可在匯入記錄中心增加「下載錯誤列 CSV / JSON」功能，讓使用者取得完整失敗資料列而不只看前幾筆樣本。
- 可考慮在設定檔檢查頁提示常見欄名差異，例如「敘述」與「作業敘述」，並建議使用 `aliases` 或 `match: contains` 明確描述來源欄位。

## 2026-06-25 multidim_event_json 多頂層事件後續改善

- 參考 `docs/multidim_event_json_multi_event_todo.md`，未來在排程允許時評估將切片合併從單一大字典 merge 改為 event-cluster merge。
- 建立 multi-event helper / selector，逐步移除 agent 內直接取 `multidim_event_json` 第一個 dict 的隱含假設。
- 評估 Editor 是否改為事件列表 + 單事件表單，以支援新增、編修、合併與拆分多個頂層事件物件。
- 若多維度分析需求提升，評估新增 event-level index 或 nested mapping，降低跨事件欄位誤配風險。

## 2026-06-26 Excel→SQL 後續改善

- 設計真正的 SQL View 自動建立流程：需定義 view name、schema、CREATE OR ALTER 權限、既有 view 更新策略、欄位引用安全檢查與審核 UI；避免只產生未執行的 view 規格。
