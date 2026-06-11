# 待辦事項（Backlog）

## 高優先度

- [ ]

## 中優先度

- [ ]

## 低優先度

- [ ]

## 技術債

- [ ]

## 未來構想

- [ ]

## 2026-06-11 後續改善建議

- [ ] 將 reset token modal 與 copy helper 抽成可重用小元件，避免 editor 與 portable auth pack 長期分岔。
- [ ] 修正 `data_ingestion/excel_to_sql/file_ops.py` 的 `datetime.utcnow()` deprecation warnings，改用 timezone-aware datetime。

---

---

## 2026-06-11 標題列導航後續改善建議

- [ ] 將 Editor 與 portable auth pack 的多層導航資料結構抽成可重用設定，降低兩份靜態 HTML 長期分岔風險。
- [ ] 在具備 Playwright / browser runtime 的環境補上標題列多層導航截圖或互動式 E2E 測試。

