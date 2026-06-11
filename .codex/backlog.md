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

- [ ] 若 audit log 筆數成長，為 `GET /v1/editor/audit-logs` 增加 `action_prefix` 或 `category` query 參數，讓文件異動與帳號操作分流改由後端完成。
- [ ] 在具備 Playwright / browser runtime 的環境補上 Editor 單欄工作區與帳號操作紀錄頁的互動式截圖或 E2E 測試。

---

## 2026-06-11 共用 audit tools 後續改善建議

- [ ] 建立正式 static assets 掛載或簡易同步腳本，確保 `api/static/audit_tools.js` 與 `portable_auth_pack/static/audit_tools.js` 不會長期分岔。
- [ ] 在具備 Playwright / browser runtime 的環境補上桌機 hover navigation、觸控 click navigation、Editor 使用統計曲線與 portable auth pack 帳號統計曲線的 E2E 測試。
- [ ] 若 usage stats 篩選需求持續擴充，可加入 action 多選、使用者多選與匯出功能。
