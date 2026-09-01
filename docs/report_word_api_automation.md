# Word 報告 API 自動化使用指南

## 適用情境

`POST /v1/report/word` 會同步執行一輪既有 Agent 流程，並直接以該輪記憶體中的 structured result 產生 DOCX。呼叫端不需要先呼叫 Chat API，也不需要等待或讀取 `state.json`。此端點不支援串流、佇列或排程。

## Request

### 已部署在 `192.168.0.133:9002` 時

`PUBLIC_API_BASE=http://192.168.0.133:9002` 是 API origin；直接開啟這個 origin 會依既有設計轉到 `/editor`。Word API 的完整 endpoint 是：

```text
POST http://192.168.0.133:9002/v1/report/word
```

因為這是 POST request，瀏覽器網址列只能送 GET，不能用「把提問接在網址後面」的方式呼叫。這不表示一定要使用 Swagger UI；可以先開啟 `http://192.168.0.133:9002/`（進入 Editor），再按 `F12` 開啟瀏覽器開發者工具的 **Console**，貼上以下 JavaScript。它使用同源相對路徑呼叫 API，完成後會直接下載 Word：

```javascript
const question = `去年加薩衝突持續造成重大平民傷亡與人道危機，停火談判、人質釋放及人道援助准入逐漸形成彼此連動的重要議題。10月間哈馬斯表示準備釋放人質並展開對話，聯合國秘書長古特雷斯對此表示歡迎，卡達與埃及亦持續參與調解；同時聯合國已備妥大批食品、藥品及帳篷等物資，但軍事行動、邊境准入、安全通行及醫療系統惡化仍限制援助落實。請持續蒐集去年加薩停火、人質談判、人道援助及平民保護相關資訊。政治外交部門掌握以色列、哈馬斯、美國、卡達、埃及及其他調解方之停火方案、人質交換條件與談判進展；國際安全部門追蹤空襲、地面軍事行動、停火違規及對平民與救援人員造成之安全影響；人道事務部門掌握食品、藥品、飲水、避難、邊境口岸與援助物資進入情形；醫療衛生部門追蹤醫院運作、醫療物資短缺、病患轉送及醫護人員安全；國際組織部門蒐集聯合國、人道協調廳、世衛組織及相關機構之聲明、數據與行動；綜合研析部門整合上述資訊，分析停火與人質談判是否實際改善人道准入與平民處境，辨識外交進展、軍事行動與人道情勢間之傳導關係，並提出談判破裂、援助受阻、醫療體系惡化及衝突再升級等後續風險。`;

const response = await fetch("/v1/report/word", {
  method: "POST",
  headers: {
    "Content-Type": "application/json",
    "X-Session-Id": `browser-gaza-${Date.now()}`
  },
  body: JSON.stringify({
    model: "SRA-Structured Retrieval Agent",
    messages: [{ role: "user", content: question }],
    stream: false,
    filename: "去年加薩衝突綜合研析.docx"
  })
});

if (!response.ok) {
  throw new Error(`HTTP ${response.status}: ${await response.text()}`);
}

const blob = await response.blob();
const downloadUrl = URL.createObjectURL(blob);
const link = document.createElement("a");
link.href = downloadUrl;
link.download = "去年加薩衝突綜合研析.docx";
document.body.appendChild(link);
link.click();
link.remove();
URL.revokeObjectURL(downloadUrl);

console.log({
  sessionId: response.headers.get("X-Session-Id"),
  turnId: response.headers.get("X-Turn-Id"),
  requestId: response.headers.get("X-Request-Id")
});
```

這個方式**不使用 FastAPI Swagger UI**，但後端 `/v1/report/word` 本身仍由既有 FastAPI 服務提供。若完全不使用 FastAPI 後端，就必須另外建立一套 HTTP server 並重新串接 Agent、Elasticsearch 與 DOCX renderer，會形成重複架構，因此本專案不建議這樣做。

### 用瀏覽器的 Swagger UI 測試

這是 `POST` API，**不能把完整提問直接接在瀏覽器網址列後面**。啟動 API 後，請開啟：

```text
http://localhost:9002/docs
```

若服務部署在其他主機，將 `localhost:9002` 換成實際 API host，例如：

```text
http://192.168.0.133:9002/docs
```

在 Swagger UI 中：

1. 展開 `POST /v1/report/word`。
2. 按 **Try it out**。
3. 將下方範例 JSON 貼入 Request body。
4. 按 **Execute**，並等待 Agent、Elasticsearch 與 LLM 完整執行。
5. 成功時 response 的 `Content-Type` 是 Word MIME；Swagger UI 會把 binary response 顯示為可下載內容。也可從瀏覽器開發者工具的 Network 面板確認 `X-Session-Id`、`X-Turn-Id` 與 `X-Request-Id`。

以下是加薩議題範例，可直接貼入 Swagger UI：

```json
{
  "model": "SRA-Structured Retrieval Agent",
  "messages": [
    {
      "role": "user",
      "content": "去年加薩衝突持續造成重大平民傷亡與人道危機，停火談判、人質釋放及人道援助准入逐漸形成彼此連動的重要議題。10月間哈馬斯表示準備釋放人質並展開對話，聯合國秘書長古特雷斯對此表示歡迎，卡達與埃及亦持續參與調解；同時聯合國已備妥大批食品、藥品及帳篷等物資，但軍事行動、邊境准入、安全通行及醫療系統惡化仍限制援助落實。請持續蒐集去年加薩停火、人質談判、人道援助及平民保護相關資訊。政治外交部門掌握以色列、哈馬斯、美國、卡達、埃及及其他調解方之停火方案、人質交換條件與談判進展；國際安全部門追蹤空襲、地面軍事行動、停火違規及對平民與救援人員造成之安全影響；人道事務部門掌握食品、藥品、飲水、避難、邊境口岸與援助物資進入情形；醫療衛生部門追蹤醫院運作、醫療物資短缺、病患轉送及醫護人員安全；國際組織部門蒐集聯合國、人道協調廳、世衛組織及相關機構之聲明、數據與行動；綜合研析部門整合上述資訊，分析停火與人質談判是否實際改善人道准入與平民處境，辨識外交進展、軍事行動與人道情勢間之傳導關係，並提出談判破裂、援助受阻、醫療體系惡化及衝突再升級等後續風險。"
    }
  ],
  "stream": false,
  "filename": "去年加薩衝突綜合研析.docx"
}
```

`去年` 會依 API 執行當下的 request-time 與服務設定時區解析；若在 2026 年執行，預期檢索年度是 2025 年。背景中的「10月間」不會自行把使用者要求的去年全年縮窄成只有 10 月。

### HTTP request contract

```http
POST /v1/report/word
Content-Type: application/json
X-Session-Id: monthly-automation-202609
```

```json
{
  "model": "SRA-Structured Retrieval Agent",
  "messages": [
    {
      "role": "user",
      "content": "請整理本月重要事件並產生分析報告"
    }
  ],
  "stream": false,
  "filename": "monthly-report.docx"
}
```

- `messages`：沿用 `/v1/chat/completions` 的訊息格式，至少應提供一筆 `user` 訊息。
- `model`：選填，預設為既有 SRA model ID。
- `stream`：只能為 `false`；同步 DOCX response 不支援 streaming。
- `filename`：選填，最長 180 字元；省略時由報告內容產生檔名。
- Session header 優先順序沿用 Chat API：`X-OpenWebUI-Chat-Id`、`X-Conversation-Id`、`X-Session-Id`；未提供時由 messages 推導。

## Response

成功時 HTTP body 就是 DOCX bytes：

- `Content-Type: application/vnd.openxmlformats-officedocument.wordprocessingml.document`
- `Content-Disposition`：可下載的 RFC-compatible 檔名。
- `Content-Length`：DOCX byte 數。
- `Cache-Control: no-store`
- `X-Session-Id`、`X-Turn-Id`、`X-Request-Id`：供自動化日誌與追蹤使用。

Agent 執行失敗時回傳 JSON error，不會回傳假 DOCX 或 fake success。

## curl 範例

```bash
curl --fail-with-body \
  -X POST 'http://localhost:9002/v1/report/word' \
  -H 'Content-Type: application/json' \
  -H 'X-Session-Id: monthly-automation-202609' \
  --data @report-request.json \
  --output monthly-report.docx \
  --dump-header monthly-report.headers
```

下載後可用下列方式驗證 Open Packaging Convention ZIP 結構：

```bash
unzip -t monthly-report.docx
```

## 從 Chat response 下載既有輪次

`POST /v1/chat/completions` 的 `choices[0].message.context.word_export` 提供：

```json
{
  "method": "GET",
  "url": "http://localhost:9002/v1/export/word?session_id=...&turn_id=...",
  "session_id": "...",
  "turn_id": "..."
}
```

此 metadata 是既有儲存快照下載方式；需要單次 API 直接得到 Word 時，應使用 `POST /v1/report/word`。兩者不可混淆：新的 POST endpoint 直接消費本輪 structured result，不以 `state.json` round-trip 產生文件。

## 目前限制

- 執行為同步模式，HTTP client / reverse proxy timeout 必須涵蓋 Agent、Elasticsearch 與 LLM 的完整執行時間。
- 目前沿用既有 Agent integration API 的存取邊界，未新增 Editor bearer token 或新的 integration authentication。
- 不包含 retry scheduler、Queue、Redis、PostgreSQL、Airflow 或 webhook。
