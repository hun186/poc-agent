# SRA-Structured Retrieval Agent Project Analysis

## 專案簡介 (Project Overview)
本專案是一個基於 **FastAPI** 和 **Elasticsearch** 建構的 **RAG (Retrieval-Augmented Generation)** 代理人系統，稱為 **SRA (Structured Retrieval Agent)**。
核心設計是透過一個 **Router Agent** 分析使用者的意圖，將任務分流到不同的子代理人（Reporting, Style Transfer, Doc Follow-up），並支援基於 Topic 的動態索引檢索。同時具備完整的對話歷史 (Session Store) 與遙測 (Telemetry) 機制。

## 技術堆疊 (Tech Stack)

### Backend & API
- **Language:** Python 3.10+
- **Web Framework:** [FastAPI](https://fastapi.tiangolo.com/) (Async Web Server)
- **Server:** Uvicorn

### LLM & Agent Framework
- **Framework:** Custom Architecture (Not relying on LangChain/LlamaIndex for core loop)
- **LLM Client:** Custom Wrapper (`agent.llm_utils.ollama_client`) supporting OpenAI-compatible APIs (likely Ollama).
- **Core Pattern:** Router-Dispatcher Pattern (`SRA_REPORT`, `SRA_STYLE`, `DOC_FOLLOWUP`, `PURE_LLM`).

### Data & Retrieval
- **Vector Database / Search Engine:** [Elasticsearch](https://www.elastic.co/)
- **Retrieval Strategy:** Hybrid Search (Keyword + Vector), Aggregation (Month/Quarter stats).
- **Session Storage:** File-based Session Store (`.agent_sessions/`).

## 模組說明 (Module Descriptions)

### 1. API Layer (`api/`)
- **[main.py](file:///c:/Users/SRAF_PoC/Downloads/poc-agent-main/api/main.py)**: 應用程式入口，初始化 FastAPI App 與 Middleware。
- **[routers/chat.py](file:///c:/Users/SRAF_PoC/Downloads/poc-agent-main/api/routers/chat.py)**: 核心 Chat Completion 端點 (`/v1/chat/completions`)，處理 Request/Response 格式轉換、Session Context 管理與使用者意圖初步判讀。

### 2. Core Agent Layer ([agent/](file:///c:/Users/SRAF_PoC/Downloads/poc-agent-main/api/routers/chat.py#165-181))
- **[agent.py](file:///c:/Users/SRAF_PoC/Downloads/poc-agent-main/agent/agent.py)**: 核心代理人邏輯。包含 [answer_with_routing](file:///c:/Users/SRAF_PoC/Downloads/poc-agent-main/agent/agent.py#256-605) (主入口) 與 [llm_route_task](file:///c:/Users/SRAF_PoC/Downloads/poc-agent-main/agent/agent.py#130-205) (任務分流器)。負責決定要呼叫哪個子代理人。
- **[report_agent.py](file:///c:/Users/SRAF_PoC/Downloads/poc-agent-main/agent/report_agent.py) (SRA_REPORT)**: 負責生成深度分析報告。流程：精煉問題 -> 數據檢索 (`data_agent`) -> 證據壓縮/篩選 -> LLM 撰寫報告 -> 表格修正。
- **[style_agent.py](file:///c:/Users/SRAF_PoC/Downloads/poc-agent-main/agent/style_agent.py) (SRA_STYLE)**: 風格模仿代理人。
- **[doc_followup_agent.py](file:///c:/Users/SRAF_PoC/Downloads/poc-agent-main/agent/doc_followup_agent.py) (DOC_FOLLOWUP)**: 針對已檢索文件的追問代理人。
- **`data_agent/`**: 負責與 Elasticsearch 互動，執行檢索與統計聚合。

### 3. Utility & Infrastructure
- **`agent/es/`**: Elasticsearch 客戶端封裝，包含 `query_body.py` (ES Query 建構) 與 `es_client.py`。
- **`config/`**: 專案設定載入（如 `bootstrap.py`）。
- **`telemetry.py`**: 遙測與日誌記錄系統。
