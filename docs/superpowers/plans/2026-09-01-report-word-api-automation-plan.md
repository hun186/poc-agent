# Report Word API Automation Implementation Plan

> **For Codex / agentic workers:** 請依本計劃逐 Task 實作，採 TDD，小步修改、小步驗證。開始前必須先閱讀 `AGENTS.md` 與 `.codex/` active memory。不要把本次範圍擴充成 Queue / Redis / PostgreSQL / Airflow。

**Goal:** 在既有 SRA Agent/OpenWebUI 架構上新增一個可由外部程式同步呼叫、直接取得 DOCX 報告的 API，並補齊 API 契約、使用文件、範例與自動測試，供大量條目後續由外部排程程式自動化使用。

**Architecture:** 保留現有 OpenWebUI `POST /v1/chat/completions` 與 `GET /v1/export/word` 行為；將「執行一輪一般 Agent 任務並取得 structured out」整理為共用 service，由 chat endpoint 與新的 `POST /v1/report/word` 共用。新的 Word API 必須直接使用本輪記憶體中的 structured result 產 DOCX，不得依賴先寫入 `.api_state/state.json` 再讀回，因此不受 `save_all_throttled()` 的寫入節流影響。

**Tech Stack:** Python 3、FastAPI、Pydantic v2、python-docx、pytest、FastAPI TestClient、既有 SRA Agent / session / telemetry / Word presenter。

**Runtime source:** `sra_api/` 是實際程式來源；`api/` 只作 compatibility import shim。除非 compatibility contract 必須調整，不要把新實作寫進頂層 `api/`。

---

## 0. 開工前必讀與基線確認

依 `AGENTS.md`，Codex 開始前依序閱讀：

1. `AGENTS.md`
2. `.codex/memory.md`
3. `.codex/architecture.md`
4. `.codex/api_contract.md`
5. `.codex/known_issues.md`
6. `.codex/decisions.md`
7. `.codex/backlog.md`

先確認相依套件：

```bash
python -m pip install -r requirements.txt
```

先跑現有相關測試，保存 baseline：

```bash
pytest -q tests/test_export_word_service.py tests/test_api_security_boundaries.py
```

若環境無法安裝或缺少套件，不得直接宣稱測試通過；依 `AGENTS.md` 記錄限制與替代驗證。

目前已知本功能相關既有結構：

- `sra_api/routers/chat.py`
  - `POST /v1/chat/completions`
  - 產生 `request_id`
  - 呼叫 `agent.agent.answer_with_routing()`
  - 將 `session_id` / `turn_id` / `request_id` 寫入 structured out
  - `save_structured_snapshot()`
  - `API_STORE.save_all_throttled()`
- `sra_api/routers/export.py`
  - `GET /v1/export/word?session_id=...&turn_id=...`
  - 目前從 `API_STORE.read_raw()` / `structured_history` 讀出 structured out 再輸出 DOCX
- `sra_api/services/export_word_service.py`
  - `ExportWordService.build_docx_bytes(out, filename=...) -> tuple[bytes, str]`
- `sra_api/services/sessions.py`
  - `save_structured_snapshot()` / `get_structured_snapshot()` / `get_structured_history()`
- `sra_api/services/api_state_store.py`
  - `save_all_throttled()` 預設 `save_min_interval_sec=1.0`
- `tests/test_export_word_service.py`
- `tests/test_api_security_boundaries.py`

---

# 1. 本次範圍

## 必做

1. 新增同步 API：`POST /v1/report/word`。
2. Request 接受報告 prompt；可選 model、filename。
3. 可選使用 `X-Session-Id`；未提供時 server 產生獨立 session id。
4. 執行既有 Agent 綜整流程。
5. 成功時直接回傳 DOCX bytes。
6. Response header 回傳本輪 `session_id`、`turn_id`，方便排程程式記錄與追查。
7. `/v1/chat/completions` 的 `message.context` 增加 `session_id`、`turn_id`、`export_word_url`，讓既有兩段式 API 也容易程式化。
8. 新 API 不透過 `state.json` 讀回剛完成報告。
9. 保持既有 OpenWebUI chat / Word 下載 contract 相容。
10. 補單元測試、API 測試、DOCX 驗證、使用文件、Python/curl 範例。
11. 更新 `.codex` project memory / API contract / architecture / decisions。

## 本次明確不做

- 不做 async job queue。
- 不新增 Redis、Celery、RQ、PostgreSQL。
- 不做 cron / Airflow scheduler server。
- 不做報告歷史 dashboard。
- 不做多 GPU 排程器。
- 不改 Elasticsearch / Query Refiner / Report Agent 的報告內容邏輯。
- 不改 Word 版型本身。
- 不把 Editor bearer token 強制套到 OpenWebUI/Agent API。
- 不在這次導入新的 integration API key；維持既有 trust boundary，安全強化留在 backlog，部署時應由內網/Nginx限制存取。

---

# 2. 新 API Contract

## POST `/v1/report/word`

### Request

```http
POST /v1/report/word
Content-Type: application/json
X-Session-Id: gaza-20260901-001   # optional
```

```json
{
  "model": "SRA-Structured Retrieval Agent",
  "prompt": "請持續蒐集去年加薩停火、人質談判、人道援助及平民保護相關資訊……",
  "filename": "gaza_report_20260901.docx"
}
```

### Pydantic model

建議：

```python
class ReportWordPayload(BaseModel):
    model: str = "SRA-Structured Retrieval Agent"
    prompt: str
    filename: str | None = None
```

Validation：

- `prompt` 去除前後空白後不可為空。
- `filename` 可省略。
- 自訂 filename 最終必須經既有 filename / Content-Disposition helper 處理。
- 不接受 caller 直接提供 server filesystem path。

### Session 規則

1. 有 `X-Session-Id`：沿用 caller 指定值。
2. 無 `X-Session-Id`：建立新的 batch/report session，例如 `report-<uuid>`。
3. 自動排程建議每次 run 使用唯一 session，例如 `gaza-20260901`，避免不同日期報告意外承接前次對話 history。
4. 若 caller 刻意重用同一 session id，則允許既有 session/history 邏輯生效；文件必須明確說明。

### Success Response

```http
HTTP/1.1 200 OK
Content-Type: application/vnd.openxmlformats-officedocument.wordprocessingml.document
Content-Disposition: attachment; ...
Content-Length: ...
Cache-Control: no-store
X-Content-Type-Options: nosniff
X-Session-Id: gaza-20260901-001
X-Turn-Id: <request_id>
```

Body：DOCX binary。

### Error Response

沿用 FastAPI JSON error：

```json
{
  "detail": "後端分析發生錯誤，請稍後再試"
}
```

要求：

- Agent 執行失敗：HTTP 500。
- DOCX 產製失敗：HTTP 500。
- Request validation 失敗：HTTP 422。
- 失敗時不可回傳半截 DOCX。

---

# 3. 共用 Agent Turn Service 設計

為了避免 `report/word` 複製一份 `chat.py` 的 agent orchestration，新增一個小型共用 service。

建議檔案：

```text
sra_api/services/agent_turn_service.py
```

建議資料型別：

```python
from dataclasses import dataclass

@dataclass
class AgentTurnResult:
    session_id: str
    turn_id: str
    out: dict
    rendered_text: str
    citations: list[dict]
```

建議 public interface：

```python
def execute_agent_turn(
    *,
    payload: ChatPayload,
    request: Request,
    session_id_override: str | None = None,
) -> AgentTurnResult:
    ...
```

責任：

- 決定/接受 session id。
- 準備 history / memory / last_structured / reuse info。
- 產生 request_id / turn_id。
- 呼叫 `answer_with_routing()`。
- 保留 `session_id` / `turn_id` / `request_id` 於 structured out。
- `save_structured_snapshot()`。
- render markdown / citations。
- 保存 session / memory。
- state persistence 仍可沿用既有行為。
- trace / telemetry 不能因 refactor 消失。

不負責：

- HTTP response shape。
- DOCX bytes。
- OpenWebUI meta task（title / tags / followups）可繼續由 chat router 在共用 service 之前處理，避免重構範圍過大。

重要：如果 Codex 發現將全部 orchestration 一次搬出 router 風險過高，可採「只抽 normal-agent path」的小步 refactor，但禁止在 `report_word.py` 複製整份 `answer_with_routing` 周邊邏輯。

---

# 4. 檔案規劃

## 建議新增

```text
sra_api/services/agent_turn_service.py
sra_api/routers/report_word.py
tests/test_agent_turn_service.py
tests/test_report_word_api.py
docs/report_word_api_automation.md
```

## 建議修改

```text
sra_api/routers/chat.py
sra_api/routers/__init__.py
sra_api/main.py
sra_api/routers/export.py            # 僅抽共用 response helper 時才改；不要破壞舊 GET contract
tests/test_api_security_boundaries.py
README.md                            # 增加文件入口即可
.codex/api_contract.md
.codex/architecture.md
.codex/decisions.md
.codex/memory.md
.codex/backlog.md                    # async queue / integration key 保留未來工作
```

若現有 import facade pattern 要求其他兼容調整，必須遵守 `.codex/decisions.md`：「runtime source 使用 sra_api/，api/ 僅 compatibility layer」。

---

# 5. Task 1 — 先把 normal Agent turn 抽成可測試的共用 service

**Files**

- Create: `sra_api/services/agent_turn_service.py`
- Modify: `sra_api/routers/chat.py`
- Test: `tests/test_agent_turn_service.py`

**Produces**

```python
@dataclass
class AgentTurnResult:
    session_id: str
    turn_id: str
    out: dict
    rendered_text: str
    citations: list[dict]
```

```python
def execute_agent_turn(
    *,
    payload: ChatPayload,
    request: Request,
    session_id_override: str | None = None,
) -> AgentTurnResult:
    ...
```

### Step 1 — 先寫 failing tests

至少涵蓋：

```python
def test_execute_agent_turn_returns_ids_and_structured_output(monkeypatch):
    ...
    assert result.session_id == "session-1"
    assert result.turn_id
    assert result.out["session_id"] == "session-1"
    assert result.out["turn_id"] == result.turn_id
```

```python
def test_execute_agent_turn_saves_snapshot_before_return(monkeypatch):
    ...
    assert saved["session_id"] == result.session_id
    assert saved["turn_id"] == result.turn_id
```

```python
def test_execute_agent_turn_preserves_answer_with_routing_inputs(monkeypatch):
    ...
    # 驗證 history / memory / reuse / request_id 等仍有傳入，避免 refactor 改變 agent behavior
```

### Step 2 — 跑測試，確認 RED

```bash
pytest -q tests/test_agent_turn_service.py
```

### Step 3 — 最小實作

抽出既有 `chat_completions()` 的一般 Agent path；不要改 Router / Query Refiner / Agent prompt。

### Step 4 — 改 chat router 使用共用 service

`POST /v1/chat/completions`：

- meta task detection 保持原行為。
- normal task 改呼叫 `execute_agent_turn()`。
- OpenAI-compatible response shape 保持。

### Step 5 — 驗證舊 chat 行為

```bash
pytest -q tests/test_agent_turn_service.py tests/test_api_security_boundaries.py
```

### Step 6 — Commit

```bash
git add sra_api/services/agent_turn_service.py sra_api/routers/chat.py tests/test_agent_turn_service.py
git commit -m "refactor: extract reusable agent turn execution"
```

---

# 6. Task 2 — 在 chat response context 暴露 export metadata

**Files**

- Modify: `sra_api/routers/chat.py`
- Test: `tests/test_agent_turn_service.py` 或新增 `tests/test_chat_api_contract.py`

現有：

```json
"context": {
  "citations": [],
  "mode": "SRA_REPORT",
  "route": "..."
}
```

更新為：

```json
"context": {
  "citations": [],
  "mode": "SRA_REPORT",
  "route": "...",
  "session_id": "...",
  "turn_id": "...",
  "export_word_url": "/v1/export/word?session_id=...&turn_id=..."
}
```

要求：

- `export_word_url` 必須 URL encode query parameter；不要手工裸拼可能含特殊字元的 session id。
- 保留既有欄位。
- 不要求 OpenWebUI 使用新欄位；它是 additive contract。

### Failing test

```python
def test_chat_context_contains_programmatic_word_export_metadata(...):
    ...
    ctx = response.json()["choices"][0]["message"]["context"]
    assert ctx["session_id"] == "session-1"
    assert ctx["turn_id"]
    assert "/v1/export/word?" in ctx["export_word_url"]
```

### 驗證

```bash
pytest -q tests/test_chat_api_contract.py tests/test_api_security_boundaries.py
```

### Commit

```bash
git commit -am "feat: expose word export metadata in chat response"
```

---

# 7. Task 3 — 新增 `POST /v1/report/word`

**Files**

- Create: `sra_api/routers/report_word.py`
- Modify: `sra_api/routers/__init__.py`
- Modify: `sra_api/main.py`
- Test: `tests/test_report_word_api.py`
- Modify test: `tests/test_api_security_boundaries.py`

### Step 1 — 先寫 route contract tests

#### Test RW-01：成功回 DOCX

```python
def test_report_word_returns_docx(monkeypatch, client):
    response = client.post(
        "/v1/report/word",
        headers={"X-Session-Id": "batch-001"},
        json={"prompt": "請產生測試報告"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    assert response.headers["content-disposition"].startswith("attachment;")
    assert response.headers["x-session-id"] == "batch-001"
    assert response.headers["x-turn-id"]
```

#### Test RW-02：直接使用本輪 result，不讀 state.json

這是本功能的關鍵 regression test：

```python
def test_report_word_does_not_read_api_state_store(monkeypatch, client):
    monkeypatch.setattr(
        report_word.API_STORE,
        "read_raw",
        lambda: (_ for _ in ()).throw(AssertionError("must not read state.json")),
        raising=False,
    )
    response = client.post("/v1/report/word", json={"prompt": "測試"})
    assert response.status_code == 200
```

若 `report_word` 根本不 import `API_STORE`，更好；測試可改用 source/static assertion 或 monkeypatch export loader，重點是證明 route 的成功路徑不經 disk export lookup。

#### Test RW-03：未提供 session id 時自動產生

```python
def test_report_word_generates_isolated_session_when_header_missing(...):
    response = client.post("/v1/report/word", json={"prompt": "測試"})
    assert response.status_code == 200
    assert response.headers["x-session-id"]
```

#### Test RW-04：自訂 filename

驗證 `Content-Disposition` 有合法 filename，且不能被 path traversal 轉成 server path。

#### Test RW-05：空 prompt

```python
def test_report_word_rejects_blank_prompt(client):
    response = client.post("/v1/report/word", json={"prompt": "   "})
    assert response.status_code == 422
```

#### Test RW-06：Agent exception

```python
def test_report_word_returns_500_when_agent_fails(monkeypatch, client):
    ...
    assert response.status_code == 500
    assert response.headers.get("content-type", "").startswith("application/json")
```

#### Test RW-07：DOCX builder exception

同樣 HTTP 500，不能產半截 DOCX。

#### Test RW-08：實際 DOCX 可開啟

不要只測 fake bytes。至少一個 integration-style test 使用真實 `ExportWordService`，用 monkeypatch 的 structured out 產檔，再由 `python-docx` 開啟：

```python
from io import BytesIO
from docx import Document


def test_report_word_response_is_valid_docx(...):
    response = ...
    assert response.content.startswith(b"PK")
    doc = Document(BytesIO(response.content))
    text = "\n".join(p.text for p in doc.paragraphs)
    assert "測試問題" in text
    assert "測試回答" in text
```

### Step 2 — 實作 route

大致責任：

```python
@router.post("/v1/report/word")
def report_word(payload: ReportWordPayload, request: Request):
    # 1. 決定 isolated/caller-provided session id
    # 2. 建 synthetic ChatPayload(messages=[ChatMessage(role="user", content=payload.prompt)])
    # 3. execute_agent_turn(...)
    # 4. ExportWordService().build_docx_bytes(result.out, filename=payload.filename)
    # 5. 回 DOCX Response + X-Session-Id + X-Turn-Id
```

注意：

- 不要用 HTTP request 呼叫自己的 `/v1/chat/completions`。
- 不要呼叫 `GET /v1/export/word`。
- 不要先從 `state.json` 撈結果。
- 必須重用 `ExportWordService` 與既有 filename helper。
- 若 `filename=None`，保留 `ExportWordService` 目前依 presentation 推導 filename 的能力。

### Step 3 — security boundary regression

目前 `.codex/api_contract.md` 明定 Agent/OpenWebUI integration routes 與 Editor auth 是不同 trust boundary。

本次先把 `/v1/report/word` 視為相同 integration API；在 `tests/test_api_security_boundaries.py` 增加：

```python
("/v1/report/word", "POST")
```

並確認 route 不意外依賴 Editor bearer token。

### Step 4 — 驗證

```bash
pytest -q tests/test_report_word_api.py tests/test_api_security_boundaries.py tests/test_export_word_service.py
```

### Step 5 — Commit

```bash
git add sra_api/routers/report_word.py sra_api/routers/__init__.py sra_api/main.py tests/test_report_word_api.py tests/test_api_security_boundaries.py
git commit -m "feat: add synchronous report word api"
```

---

# 8. Task 4 — 補自動化使用文件與範例

**Files**

- Create: `docs/report_word_api_automation.md`
- Modify: `README.md`

文件至少包含：

1. 使用情境。
2. 架構圖（文字即可）。
3. API request / response contract。
4. curl 範例。
5. Python `requests` 範例。
6. 多條目迴圈範例。
7. timeout 建議。
8. retry 原則。
9. session id 命名建議。
10. Word filename 命名建議。
11. 目前是同步 API 的限制。
12. 未來大量併發才考慮 async job queue。
13. 安全提醒：目前 integration API 依既有 contract 為公開 route，應放內網或 Nginx/gateway 存取控制後方。

## curl 範例

```bash
curl -X POST "http://127.0.0.1:9002/v1/report/word" \
  -H "Content-Type: application/json" \
  -H "X-Session-Id: gaza-20260901" \
  -d '{
    "prompt": "請持續蒐集去年加薩停火、人質談判、人道援助及平民保護相關資訊……",
    "filename": "gaza_20260901.docx"
  }' \
  --output gaza_20260901.docx
```

## Python 單筆範例

```python
from pathlib import Path
import requests

url = "http://127.0.0.1:9002/v1/report/word"

response = requests.post(
    url,
    headers={"X-Session-Id": "gaza-20260901"},
    json={
        "prompt": "請持續蒐集去年加薩停火、人質談判、人道援助及平民保護相關資訊……",
        "filename": "gaza_20260901.docx",
    },
    timeout=900,
)
response.raise_for_status()

Path("gaza_20260901.docx").write_bytes(response.content)
print("session:", response.headers.get("X-Session-Id"))
print("turn:", response.headers.get("X-Turn-Id"))
```

## 多條目序列批次範例

本次文件先示範「外部 scheduler sequential loop」，不要在 server 內偷偷加入 queue：

```python
from datetime import date
from pathlib import Path
import requests

REPORTS = [
    {"id": "gaza", "prompt": "..."},
    {"id": "china-korea-fta", "prompt": "..."},
]

out_dir = Path("reports") / date.today().isoformat()
out_dir.mkdir(parents=True, exist_ok=True)

for item in REPORTS:
    session_id = f"{item['id']}-{date.today():%Y%m%d}"
    filename = f"{session_id}.docx"
    r = requests.post(
        "http://127.0.0.1:9002/v1/report/word",
        headers={"X-Session-Id": session_id},
        json={"prompt": item["prompt"], "filename": filename},
        timeout=900,
    )
    r.raise_for_status()
    (out_dir / filename).write_bytes(r.content)
```

Retry 文件原則：

- network error / timeout / HTTP 5xx：可有限次 retry + backoff。
- HTTP 4xx：視為 request/config error，不應無限 retry。
- 由於目前是同步 API，scheduler 必須設定足以涵蓋 Agent 長流程的 timeout。
- 若未來同時跑大量 report 造成 GPU 壅塞，再進 Phase 3 Job Queue；本次不做。

README 只需要加一個簡短入口，連到 `docs/report_word_api_automation.md`，避免 README 膨脹。

### Commit

```bash
git add docs/report_word_api_automation.md README.md
git commit -m "docs: document report word automation api"
```

---

# 9. Task 5 — API 契約與長期專案記憶更新

**Files**

- Modify: `.codex/api_contract.md`
- Modify: `.codex/architecture.md`
- Modify: `.codex/decisions.md`
- Modify: `.codex/memory.md`
- Modify: `.codex/backlog.md`

## `.codex/api_contract.md`

新增：

- `POST /v1/report/word`
- request model
- optional `X-Session-Id`
- success headers
- DOCX MIME
- 422/500 behavior
- `/v1/chat/completions` 新增 additive context metadata

## `.codex/architecture.md`

新增資料流：

```text
OpenWebUI
   -> POST /v1/chat/completions
   -> shared AgentTurnService
   -> Agent

External Scheduler / Python
   -> POST /v1/report/word
   -> shared AgentTurnService
   -> Agent
   -> ExportWordService
   -> DOCX bytes
```

說明 `/v1/report/word` 不依賴 disk round-trip。

## `.codex/decisions.md`

新增決策：

- interactive chat 與 programmatic report 共用同一 Agent execution service。
- direct Word API 用當輪 structured result 直接產 DOCX，避免 state persistence throttle 造成 race。
- 本階段採 synchronous API；queue 是下一階段，而不是這次的隱含依賴。

## `.codex/backlog.md`

保留/補充：

- Phase 3：async report jobs / priority queue / retry / status API。
- integration API key / gateway auth（不得重用 Editor bearer token）。
- 大量併發壓測與 GPU dispatch policy。

## `.codex/memory.md`

完成後記錄：

- 修改目的。
- 新增 route。
- 共用 service。
- 測試結果與通過數。
- 若有無法驗證項目，明確列出。

### Commit

```bash
git add .codex/api_contract.md .codex/architecture.md .codex/decisions.md .codex/memory.md .codex/backlog.md
git commit -m "docs: record report word api architecture"
```

---

# 10. Task 6 — 最終 regression 與手動 API smoke test

## Automated tests

至少跑：

```bash
pytest -q \
  tests/test_agent_turn_service.py \
  tests/test_chat_api_contract.py \
  tests/test_report_word_api.py \
  tests/test_export_word_service.py \
  tests/test_api_security_boundaries.py
```

再跑完整 suite：

```bash
pytest -q tests
```

若完整 suite 有既有失敗：

- 必須先判斷是否為本次 regression。
- 不得把失敗一律標成「既有問題」。
- 若確認既有，記錄測試名稱與證據至 `.codex/known_issues.md` / `.codex/memory.md`。

## Manual smoke test

啟動 API（依本 repo 既有啟動方式）：

```bash
uvicorn api.main:app --host 0.0.0.0 --port 9002
```

測試新 endpoint：

```bash
curl -v -X POST "http://127.0.0.1:9002/v1/report/word" \
  -H "Content-Type: application/json" \
  -H "X-Session-Id: smoke-20260901" \
  -d '{"prompt":"請整理測試報告","filename":"smoke.docx"}' \
  --output smoke.docx
```

檢查：

```bash
python - <<'PY'
from docx import Document

doc = Document("smoke.docx")
print("paragraphs=", len(doc.paragraphs))
assert len(doc.paragraphs) > 0
PY
```

再確認舊流程仍可用：

1. `POST /v1/chat/completions`
2. 從 response context 取得 `session_id` / `turn_id`
3. `GET /v1/export/word?session_id=...&turn_id=...`
4. Word 可正常開啟

---

# 11. 必須通過的驗收條件

- [ ] `POST /v1/report/word` 可由 curl/Python 呼叫。
- [ ] 成功時 HTTP 200 + 正確 DOCX MIME。
- [ ] 下載檔可由 `python-docx` 開啟。
- [ ] Word 內容來自本輪 Agent structured result，不是 fake/stub。
- [ ] Response 有 `X-Session-Id`、`X-Turn-Id`。
- [ ] 不傳 `X-Session-Id` 時會產生新的 isolated session。
- [ ] 新 route 的成功路徑不呼叫 `API_STORE.read_raw()` 取得本輪報告。
- [ ] `/v1/chat/completions` 保持 OpenAI-compatible response，僅 additive 增加 export metadata。
- [ ] `GET /v1/export/word` 舊功能仍正常。
- [ ] OpenWebUI integration routes 不意外被 Editor auth 擋住。
- [ ] Agent / ES / Query Refiner / Report prompt 行為沒有為了新 API 被重寫。
- [ ] 自動測試新增且通過。
- [ ] `docs/report_word_api_automation.md` 有 curl / Python / batch 例子。
- [ ] `.codex/api_contract.md`、`architecture.md`、`decisions.md`、`memory.md` 已更新。
- [ ] 若測試受環境限制，已依 AGENTS 規則留下驗證證據與 known issue。

---

# 12. Review 注意事項

Codex 完成後自行檢查：

1. 有沒有把 runtime code 寫到錯誤的 `api/` shim？
2. 有沒有在 `report_word.py` 複製大段 `chat.py` orchestration？若有，應抽共用 service。
3. 新 Word API 是否仍依賴 `state.json` 讀回本輪結果？若是，設計未完成。
4. 是否意外更動了 Report Agent prompt / retrieval 邏輯？本次不應改。
5. 是否意外要求 Editor bearer token？本次不應改 trust boundary。
6. 是否把 queue / Redis / DB 偷塞進本次 PR？若有，移除並列 backlog。
7. 是否只有 fake bytes 測試，卻沒有真實 DOCX 可解析測試？必須補。
8. 是否沒有驗證原本 `/v1/export/word`？必須補 regression。
9. 是否留下 `TODO` / `TBD` / STUB 卻宣稱完成？不允許。

---

# 13. 建議 PR 切分

如果 Codex 可以分 commit，建議：

1. `refactor: extract reusable agent turn execution`
2. `feat: expose word export metadata in chat response`
3. `feat: add synchronous report word api`
4. `docs: document report word automation api`
5. `docs: record report word api architecture`

不要把不相關 refactor 混進 PR。

---

# 14. 給 Codex 的啟動提問（推薦）

把本計劃存入 repo，例如：

```text
docs/superpowers/plans/2026-09-01-report-word-api-automation.md
```

然後對 Codex 說：

> 請依 `docs/superpowers/plans/2026-09-01-report-word-api-automation.md` 完整實作「自動化 API 直接回傳 Word 報告」功能。開始前請依 `AGENTS.md` 順序讀取 `.codex` 專案記憶，先確認目前程式碼與計劃假設是否一致；若文件與程式碼衝突，以程式碼為準並同步修正文件。請採 TDD，先補 failing tests，再做最小實作。這次只做 synchronous `/v1/report/word`、共用 Agent turn service、chat export metadata、測試與文件；不要擴充到 Queue、Redis、PostgreSQL、Airflow 或其他排程基礎設施，也不要修改 Agent/ES/Query Refiner/Report Prompt 的核心行為。新的 Word endpoint 必須直接使用本輪 structured result 產生 DOCX，不得依賴 `state.json` round-trip。完成後跑 targeted tests 與完整 `pytest tests`，提供實際驗證結果，並依 `AGENTS.md` 更新 `.codex/memory.md`、`api_contract.md`、`architecture.md`、`decisions.md`、`backlog.md`。最後請列出修改檔案、API 使用方式、測試結果、已知限制與後續 Phase 3 建議。

---

# 15. 如果不想先把計劃檔放進 repo，可直接這樣問 Codex

> 我要在現有 SRA Agent/OpenWebUI 專案新增「外部程式呼叫 API 後直接取得 DOCX 報告」功能。請先讀 `AGENTS.md` 與 `.codex` active memory，再檢查 `sra_api/routers/chat.py`、`sra_api/routers/export.py`、`sra_api/services/export_word_service.py`、`sra_api/services/sessions.py`、`sra_api/services/api_state_store.py` 以及既有 Word/API tests。請保持 `/v1/chat/completions` 與 `/v1/export/word` 相容，新增同步 `POST /v1/report/word`。不要讓新 endpoint 先寫 `state.json` 再讀回；請抽出共用的 normal Agent turn execution service，讓 chat 與 report-word API 共用同一執行路徑，並直接拿本輪 structured out 呼叫 `ExportWordService`。新 API 成功時回 DOCX binary，response headers 至少包含 `X-Session-Id`、`X-Turn-Id`；`X-Session-Id` 可由 caller 指定，缺省時自動建立獨立 session。另在 chat response context 增加 `session_id`、`turn_id`、`export_word_url`。請採 TDD，補成功、空 prompt、agent error、docx error、custom filename、auto session、真實 DOCX 可解析、不得讀 state.json、舊 export regression、public integration boundary 等測試；補 `docs/report_word_api_automation.md` 的 curl/Python/批次使用例，並更新 `.codex` 文件。這次不要做 Queue/Redis/DB/Airflow，不修改 retrieval/report prompt 核心邏輯。完成後跑 targeted tests 與完整 test suite，回報實際結果與限制。

---

# 16. 後續 Phase 3（本次不實作）

等同步 API 穩定、實際跑過一段時間，再另案評估：

```text
POST /v1/report-jobs
GET  /v1/report-jobs/{job_id}
GET  /v1/report-jobs/{job_id}/word
```

搭配：

- persistent job DB
- priority queue
- retry / backoff
- worker concurrency
- GPU dispatch
- failed job replay
- report retention
- API integration credential
- observability / metrics

Phase 3 必須另開設計與更新計劃，不要在這次 PR 順手實作。
