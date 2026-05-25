# Local LLM Notebook

一個可在地端部署的文件問答系統，使用 FastAPI、Jinja2、MSSQL、ChromaDB 與 Ollama 建構。系統支援文件群組管理、文件上傳、chunk 化儲存，以及依群組範圍限制的 RAG 問答流程，適合作為本地知識庫問答與 RAG 架構練習專案。

## 專案目標

讓使用者在指定文件群組內提問，並由本地模型根據系統內部文件內容回答，而非依賴模型本身的通用知識。這種設計提升了回答的可追溯性，並降低模型胡亂補充外部知識的風險。

---

## 主要功能

### 身份驗證與權限
- Session 登入，`username` 與 `role` 存在 server-side session cookie，URL 不暴露帳號資訊；支援 `/logout` 登出。
- Admin / User 雙角色，Admin 才能上傳、刪除文件與管理群組及帳號。

### Admin 帳號管理
- 新增使用者（設定 username、密碼、角色）。
- 列出所有使用者帳號與角色。
- 刪除使用者帳號（不可刪除自己）。
- 密碼以 bcrypt 雜湊儲存，舊帳號可透過 `migrate_passwords.py` 一鍵遷移至雜湊版本。

### 文件管理
- 文件群組新增、刪除與管理。
- 文件上傳（PDF / TXT），自動切 chunk 並同步建立向量索引（ChromaDB），上傳後向量搜尋立刻可用。
- 刪除文件時同步清除 ChromaDB 向量。
- 上傳單檔大小限制（預設 20 MB，可透過 `.env` 調整）。
- SHA-256 去重，同一份檔案不會重複上傳。

### RAG 問答
- 使用者依群組範圍提問。
- 中英文混合查詢自動切分（`dict怎麼用` → `['dict', '怎麼用']`），避免整句當成一個搜尋詞。
- 使用 Ollama 進行查詢重寫與答案生成。
- **四路檢索**融合：原始 keyword、重寫 keyword、原始向量、重寫向量（ChromaDB）。
- RRF（Reciprocal Rank Fusion）融合四路結果。
- Ollama rerank 並行評分（三路同時發送），評分 < 2 自動 fallback。
- 切 chunk 時在句號 / 換行處切，不硬切斷句子。
- 顯示參考來源與 chunk debug 資訊，方便調整 RAG 表現。

### 可維運性
- 統一 logging，輸出至終端機與 `logs/app.log`，並自動 rotate。
- 所有設定（Ollama URL、模型名稱、DB 連線、session secret）集中在 `.env`，不硬編碼。

---

## 系統架構

### 後端分層

```
routers → services → repositories → DB / ChromaDB / Ollama
```

| 層級 | 說明 |
|------|------|
| `routers` | 接收 HTTP 請求，驗證 session，組合 service 呼叫，回填模板 |
| `services` | 業務邏輯，包含 RAG 流程、embedding、文件處理、帳號管理 |
| `repositories` | 資料存取，SQL Server 與 ChromaDB 操作 |

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
| `documents` | 文件主檔與 metadata（含 SHA-256 hash 做去重） |
| `document_chunks` | 切割後的 chunk（含 `chunk_index` 供相鄰擴展用） |
| `users` | 使用者帳號、bcrypt 雜湊密碼與角色（`admin` / `user`） |

ChromaDB 向量資料庫（`chroma_db/`）：Collection `document_chunks`，儲存每個 chunk 的 embedding，metadata 含 `group_id` 供群組過濾。

### 模型層

| 用途 | 模型 | 說明 |
|------|------|------|
| Embedding | `mxbai-embed-large` | 將 chunk 與查詢向量化 |
| 查詢重寫 | `llama3:latest` | 把自然語言問題改寫成技術文件檢索詞 |
| Rerank 評分 | `llama3:latest` | 對候選 chunk 評 0–5 分（三路並行發送） |
| 答案生成 | `llama3:latest` | 根據 chunk 產生 grounded answer |

---

## RAG 流程

```
使用者提問
    ↓
查詢 Tokenize（中英文切分 + bigram）
    ↓
查詢重寫（Ollama）
    ↓
四路檢索（原始 keyword / 重寫 keyword / 原始向量 / 重寫向量）
    ↓
RRF 融合（取 top 15）
    ↓
並行 Rerank（top 3，三路同時評分，< 2 fallback）
    ↓
相鄰 chunk 擴展（前後各 +1 chunk）
    ↓
答案生成（Ollama，僅根據文件內容回答）
```

### 四路檢索說明

| 路 | 方式 | 查詢 |
|----|------|------|
| 原始 keyword | SQL LIKE + 相關性排序 | 原始問題 |
| 重寫 keyword | SQL LIKE + 相關性排序 | Ollama 重寫後查詢 |
| 原始向量 | ChromaDB top 25 | 原始問題 embedding |
| 重寫向量 | ChromaDB top 25 | 重寫後查詢 embedding |

SQL keyword 搜尋取 TOP 200 後由 Python 重新加權評分，過濾 score=0 的無關結果。RRF 以排名而非原始分數整合四路結果。

---

## 環境需求

- Python 3.11+
- SQL Server（LocalDB 或 SQLEXPRESS 皆可）
- [Ollama](https://ollama.com/) 本地運行，並拉取以下模型：

```bash
ollama pull llama3
ollama pull mxbai-embed-large
```

---

## 快速開始

```bash
# 1. 安裝依賴
uv sync

# 2. 建立設定檔
copy .env.example .env
# 打開 .env，把 SESSION_SECRET 改成任意隨機字串

# 3. 建立資料庫
# 在 SQL Server 建立 local_llm_notebook 資料庫後執行 schema.sql

# 4. 啟動伺服器
uv run uvicorn main:app --reload
```

### 密碼遷移（舊帳號）

若資料庫中存有明文密碼的舊帳號，執行以下腳本一鍵遷移為 bcrypt 雜湊：

```bash
uv run python scripts/migrate_passwords.py
```

---

## 專案目錄

```text
├─ main.py                   # FastAPI 進入點、SessionMiddleware、logging 設定
├─ .env.example              # 設定檔範本（複製為 .env 後填入實際值）
├─ schema.sql                # 建立資料庫資料表的 SQL 腳本
├─ logs/                     # 自動產生的 log 檔（app.log，自動 rotate）
├─ chroma_db/                # ChromaDB 向量資料庫（本地持久化）
├─ core/
│  ├─ config.py              # 從 .env 讀取所有設定
│  ├─ database.py            # SQL Server 連線
│  └─ template.py            # Jinja2 模板初始化
├─ repositories/
│  ├─ user_repository.py     # 使用者 CRUD（新增、查詢、列表、刪除）
│  ├─ group_repository.py    # 文件群組 CRUD
│  ├─ document_repository.py # 文件主檔 CRUD
│  ├─ chunk_repository.py    # chunk 查詢、相鄰 chunk 擴展、相關性排序搜尋
│  └─ vector_repository.py   # ChromaDB 操作（upsert、query、delete）
├─ services/
│  ├─ auth_service.py        # 登入驗證、bcrypt 密碼比對
│  ├─ group_service.py       # 群組業務邏輯
│  ├─ file_service.py        # PDF / TXT 文字擷取
│  ├─ document_service.py    # 文字切 chunk（尊重句子邊界）
│  ├─ embedding_service.py   # Ollama embedding + 自動向量索引
│  └─ rag_service.py         # 完整 RAG 流程（tokenize、四路檢索、RRF、並行 rerank、生成）
├─ routers/
│  ├─ auth.py                # 登入、登出、session 寫入
│  ├─ admin.py               # 上傳、群組管理、文件刪除、帳號管理
│  └─ user.py                # 提問與 RAG 流程觸發
├─ scripts/
│  ├─ index_chunks.py        # 手動全量重建向量索引（補救用）
│  └─ migrate_passwords.py   # 將舊明文密碼一鍵遷移為 bcrypt 雜湊
├─ templates/
│  ├─ admin/
│  └─ user/
└─ static/
   └─ style.css
```
