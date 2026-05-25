# Local LLM Notebook

一個可在地端部署的文件問答系統，使用 FastAPI、Jinja2、MSSQL、ChromaDB 與 Ollama 建構。系統支援文件群組管理、文件上傳、文件 chunk 化儲存，以及依群組範圍限制的 RAG 問答流程，適合做為本地知識庫問答與 RAG 架構練習專案。

## 專案目標

本專案的核心目標是讓使用者能夠在指定文件群組內提問，並由本地模型根據系統內部文件內容回答問題，而不是直接依賴模型本身的通用知識。這種設計可提升回答的可追溯性，並降低模型直接胡亂補充外部知識的風險。

## 主要功能

- Session 身份驗證，登入後 username 存在 server-side session，URL 不暴露帳號資訊；支援 `/logout` 登出。
- Admin / User 角色區分，Admin 才能上傳、刪除文件與管理群組。
- 文件群組新增、刪除與管理。
- 文件上傳（PDF / TXT），自動切 chunk 並同步建立向量索引（ChromaDB），上傳後向量搜尋立刻可用；刪除文件時同步清除 ChromaDB 向量。
- 上傳單檔大小限制（預設 20MB，可透過 `.env` 調整）。
- SHA-256 去重，同一份檔案不會重複上傳。
- 使用者依群組範圍提問。
- 中英文混合查詢自動切分（`dict怎麼用` → `['dict', '使用'...]`），避免整句當成一個搜尋詞。
- 使用 Ollama 進行查詢重寫與答案生成。
- **四路檢索**融合：原始 keyword、重寫 keyword、原始向量、重寫向量（ChromaDB）。
- 使用 RRF（Reciprocal Rank Fusion）融合四路結果。
- Ollama rerank 並行評分（三路同時發送），評分 < 2 自動 fallback，避免爛結果進 LLM。
- 切 chunk 時在句號/換行處切，不硬切斷句子。
- 顯示參考來源與 chunk debug 資訊，方便調整 RAG 表現。
- 統一 logging，輸出至終端機與 `logs/app.log`，並自動 rotate。
- 所有設定（Ollama URL、模型名稱、DB 連線、session secret）集中在 `.env`，不硬編碼。

## 系統架構

### 身份驗證

使用 Starlette `SessionMiddleware`，登入後將 `username` 與 `role` 存入 server-side session cookie。每個受保護的路由在 handler 內直接讀取 session，未登入則 redirect 回登入頁。

### 前端

前端使用 Jinja2 模板渲染 HTML，主要提供：

- 文件群組選擇（雙欄拖拉介面）。
- 問題輸入。
- 系統回答與來源標註顯示。
- chunk debug 顯示（chunk 內容、分數、命中關鍵字）。

### 後端

後端以 FastAPI 建立路由與服務邏輯，採分層設計：

```
routers → services → repositories → DB / ChromaDB / Ollama
```

- `routers`：接收 HTTP 請求，session 驗證，組合 service 呼叫，回填模板。
- `services`：業務邏輯，包含 RAG 流程、embedding、文件處理。
- `repositories`：資料存取，SQL Server 與 ChromaDB 操作。

### 設定管理

所有可調參數集中在 `core/config.py`，透過 `.env` 覆寫：

| 變數 | 預設值 | 說明 |
|------|--------|------|
| `OLLAMA_URL` | `http://localhost:11434` | Ollama 服務位址 |
| `EMBED_MODEL` | `mxbai-embed-large` | Embedding 模型 |
| `LLM_MODEL` | `llama3:latest` | 問答 / rerank / rewrite 模型 |
| `DB_CONNECTION_STRING` | SQLEXPRESS localhost | SQL Server 連線字串 |
| `SESSION_SECRET` | （需自行設定） | Session 加密金鑰 |
| `MAX_UPLOAD_MB` | `20` | 單檔上傳大小上限 |

### 資料庫

SQL Server 核心資料表（建表腳本見 `schema.sql`）：

| 資料表 | 說明 |
|--------|------|
| `document_groups` | 文件群組 |
| `documents` | 文件主檔與 metadata（含 SHA256 hash 做去重） |
| `document_chunks` | 切割後的 chunk（含 `chunk_index` 供相鄰擴展用） |
| `users` | 使用者帳號與角色（`admin` / `user`） |

ChromaDB 向量資料庫（`chroma_db/`）：

- Collection `document_chunks`：儲存每個 chunk 的 embedding，metadata 含 `group_id` 供群組過濾。文件刪除時同步清除。

### 模型層

| 用途 | 模型 | 說明 |
|------|------|------|
| Embedding | `mxbai-embed-large` | 將 chunk 與查詢向量化 |
| 查詢重寫 | `llama3:latest` | 把自然語言問題改寫成技術文件檢索詞 |
| Rerank 評分 | `llama3:latest` | 對候選 chunk 評 0–5 分（三路並行發送） |
| 答案生成 | `llama3:latest` | 根據 chunk 產生 grounded answer |

## 系統流程

### 1. 文件匯入

上傳時系統會：
1. 檢查檔案大小，超過上限直接拒絕。
2. 計算 SHA-256 hash，重複檔案跳過。
3. 解析文字內容（PDF / TXT）。
4. 儲存文件 metadata 到 `documents`。
5. 切成 chunks（每塊約 800 字，重疊 120 字，在句號/換行處切），寫入 `document_chunks`。
6. 自動呼叫 Ollama embedding，將所有 chunk 寫入 ChromaDB——上傳後向量搜尋立刻可用。

### 2. 使用者提問

使用者在前端選定一個或多個群組後輸入問題。

### 3. 查詢 Tokenize

系統對查詢做智慧切分：

- 按空白與標點分割。
- 在中英文交界處自動切開（`dict怎麼用` → `['dict', '怎麼用']`）。
- 對長 CJK 片段產生 2-gram bigram（`怎麼使用` → 額外加 `['怎麼', '使用']`），避免整句當一個詞找不到 chunk。

### 4. 查詢重寫

Ollama 把原始問題改寫成更像技術文件的檢索詞，例如：

```
dict怎麼使用的 語法是甚麼 → Python dict 用法 dictionary 語法
```

### 5. 四路檢索

同時執行四路搜尋：

| 路 | 方式 | 查詢 |
|----|------|------|
| 原始 keyword | SQL LIKE + 相關性排序 | 原始問題 |
| 重寫 keyword | SQL LIKE + 相關性排序 | Ollama 重寫後查詢 |
| 原始向量 | ChromaDB top 25 | 原始問題 embedding |
| 重寫向量 | ChromaDB top 25 | 重寫後查詢 embedding |

SQL keyword 搜尋取 TOP 200 後由 Python 重新加權評分，過濾 score=0 的無關結果。

### 6. RRF 結果融合

四路結果用 RRF（Reciprocal Rank Fusion）融合，以排名而非原始分數整合，融合後取 top 15。

### 7. Rerank

對融合後的 top 3 候選 chunk，並行發送三個 Ollama 評分請求（各評 0–5 分）。若最高分 < 2，放棄 rerank 結果，直接用 RRF 排名前 5 的 chunk，避免全部都是爛結果還進 LLM。

### 8. 相鄰 chunk 擴展

對 top 5 chunk，根據 `document_id` 與 `chunk_index` 抓取前後各一個 chunk，補足上下文，避免答案被切在 chunk 邊界。

### 9. 答案生成

將整理後的 chunk 丟給 Ollama，要求模型只能根據文件內容回答，資訊不足時明確表示無法確定，並輸出來源標註。

## 環境需求

- Python 3.11+
- SQL Server（LocalDB 或 SQLEXPRESS 皆可）
- [Ollama](https://ollama.com/) 本地運行，並拉取以下模型：
  ```
  ollama pull llama3
  ollama pull mxbai-embed-large
  ```

## 快速開始

```bash
# 1. 安裝依賴
uv sync

# 2. 建立設定檔
copy .env.example .env
# 然後打開 .env，把 SESSION_SECRET 改成任意隨機字串

# 3. 建立資料庫
# 在 SQL Server 建立 local_llm_notebook 資料庫後，執行：
# schema.sql

# 4. 啟動伺服器
uv run uvicorn main:app --reload
```

## 專案目錄

```text
├─ main.py                  # FastAPI 進入點、SessionMiddleware、logging 設定
├─ .env.example             # 設定檔範本（複製為 .env 後填入實際值）
├─ schema.sql               # 建立資料庫資料表的 SQL 腳本
├─ logs/                    # 自動產生的 log 檔（app.log，自動 rotate）
├─ chroma_db/               # ChromaDB 向量資料庫（本地持久化）
├─ core/
│  ├─ config.py             # 從 .env 讀取所有設定
│  ├─ database.py           # SQL Server 連線
│  └─ template.py           # Jinja2 模板初始化
├─ repositories/
│  ├─ group_repository.py
│  ├─ document_repository.py
│  ├─ chunk_repository.py   # 含相鄰 chunk 查詢、依文件 ID 查詢、相關性排序搜尋
│  └─ vector_repository.py  # ChromaDB 操作（upsert、query、delete）
├─ services/
│  ├─ auth_service.py
│  ├─ file_service.py       # PDF / TXT 文字擷取
│  ├─ document_service.py   # 文字切 chunk（尊重句子邊界）
│  ├─ embedding_service.py  # Ollama embedding + 自動向量索引
│  └─ rag_service.py        # 完整 RAG 流程（tokenize、四路檢索、RRF、並行 rerank、生成）
├─ routers/
│  ├─ auth.py               # 登入、登出、session 寫入
│  ├─ admin.py              # 上傳（含大小限制）、群組管理、刪除（含向量清除）
│  └─ user.py               # 提問與 RAG 流程觸發
├─ scripts/
│  └─ index_chunks.py       # 手動全量重建向量索引（補救用）
├─ templates/
│  ├─ admin/
│  └─ user/
└─ static/
   └─ style.css
```
