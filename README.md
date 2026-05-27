# Local LLM Notebook

一個可在地端部署的文件問答系統，使用 FastAPI、Jinja2、SQL Server、ChromaDB 與 Ollama 建構。系統支援文件群組管理、使用者群組權限控管、文件上傳與 chunk 化儲存，以及依群組範圍限制的 RAG 問答流程，適合作為本地知識庫問答與 RAG 架構練習專案。

## 專案目標

讓使用者在指定文件群組內提問，並由本地模型根據系統內部文件內容回答，而非依賴模型本身的通用知識。這種設計提升了回答的可追溯性，並降低模型胡亂補充外部知識的風險。所有資料與模型皆在本地端執行，不對外傳送任何資料。

---

## 主要功能

### 身份驗證與權限
- Session 登入，`username`、`role`、`user_id` 存在 server-side session cookie，URL 不暴露帳號資訊。
- Admin / User 雙角色，Admin 才能上傳、刪除文件與管理群組及帳號。

### Admin — 帳號管理
- 新增使用者（設定 username、密碼、角色）。
- 列出所有使用者帳號與角色，顯示各帳號已授權的群組數量。
- 刪除使用者帳號。
- 密碼以 PBKDF2-SHA256 雜湊儲存，舊帳號可透過 `migrate_passwords.py` 一鍵遷移。

### Admin — 群組權限管理
- 為每位 user 角色的帳號指派可存取的文件群組（多選 checkbox）。
- 未指派任何群組時，預設可存取全部群組（向下相容）。
- Admin 角色永遠可存取全部群組。

### Admin — 文件管理
- 文件群組新增、刪除（需先清空群組內文件）。
- 文件上傳支援 **PDF / TXT / DOCX**，自動切 chunk 並以 BackgroundTask 建立向量索引，上傳後立即可搜尋。
- 上傳頁面顯示 XHR 真實傳輸進度條與每個檔案的處理結果，不需等待頁面重新整理。
- 刪除文件時同步清除 ChromaDB 向量。
- 上傳單檔大小限制（預設 20 MB，可透過 `.env` 調整）。
- SHA-256 去重，同一份檔案不會重複上傳。

### Admin — 使用統計
- **每日問答量**：直方圖，可自訂日期範圍，快速切換近 7 天 / 近 30 天。
- **各群組查詢次數**：直方圖，可勾選特定群組比較。
- **使用時段分析**：0–23 時累計查詢次數，尖峰時段以橘色高亮。
- **回答品質摘要**：顯示累計 👍 / 👎 數量與滿意度百分比。
- 一鍵匯出 Excel（四個 Sheet：每日問答量、各群組查詢次數、使用時段、回答品質）。

### User — 問答
- 雙側列表選擇可查詢的群組（依權限過濾），只在選定群組內檢索。
- RAG 問答以 Server-Sent Events 逐字串流輸出，顯示 chunk 來源與分數。
- Streaming 完成後顯示 👍 / 👎 回饋按鈕，點擊後寫入資料庫。
- 多輪對話：Session 保存近 10 筆歷史作為 LLM 上下文（送給 LLM 時只取最近 3 筆）。

### User — 對話記錄
- 每次問答（含 streaming）自動持久化存入 DB。
- `/user/history` 頁面可查閱最近 50 筆歷史問答與時間戳記。

### 可維運性
- 統一 logging，輸出至終端機與 `logs/app.log`，並自動 rotate（5 MB，保留 3 份）。
- 所有設定集中在 `.env`，不硬編碼。

---

## 系統架構

### 後端分層

```
Browser
    ↓ HTTP
Routers（auth / admin / user）
    ↓
Services（RAG / embedding / document / file / auth）
    ↓
Repositories（SQL Server / ChromaDB）
    ↓
Ollama（本地 LLM）
```

| 層級 | 說明 |
|------|------|
| `routers` | 接收 HTTP 請求，驗證 session，組合 service 呼叫，回填模板 |
| `services` | 業務邏輯，包含 RAG 流程、embedding、文件處理 |
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

SQL Server 核心資料表（初始建表腳本見 `schema.sql`，後續異動見 `scripts/migration_v*.sql`）：

| 資料表 | 說明 |
|--------|------|
| `users` | 使用者帳號、雜湊密碼、角色（`admin` / `user`） |
| `document_groups` | 文件群組（名稱、說明） |
| `documents` | 文件主檔與 metadata（含 SHA-256 hash 做去重） |
| `document_chunks` | 切割後的 chunk（含 `chunk_index` 供相鄰擴展用） |
| `user_group_permissions` | 使用者 ↔ 群組 多對多存取權限 |
| `chat_history` | 對話記錄（問題、回答、群組 ID 清單、回饋分數、時間戳記） |

ChromaDB 向量資料庫（`chroma_db/`）：Collection `document_chunks`，儲存每個 chunk 的 embedding，metadata 含 `group_id` 供群組過濾。

### 模型層

| 用途 | 模型 | 說明 |
|------|------|------|
| Embedding | `mxbai-embed-large` | 將 chunk 與查詢向量化 |
| 查詢重寫 | `llama3:latest` | 把自然語言問題改寫成技術文件檢索詞 |
| Rerank 評分 | `llama3:latest` | 對候選 chunk 評 0–5 分（並行發送） |
| 答案生成 | `llama3:latest` | 根據 chunk 產生 grounded answer |

---

## RAG 流程

```
使用者提問
    ↓
查詢 Tokenize（中英文切分 + bigram + 停用詞過濾）
    ↓
查詢重寫（Ollama）
    ↓
四路檢索
  ├─ 原始問題 → SQL keyword 搜尋
  ├─ 重寫問題 → SQL keyword 搜尋
  ├─ 原始問題 → ChromaDB 向量搜尋（top 25）
  └─ 重寫問題 → ChromaDB 向量搜尋（top 25）
    ↓
RRF 融合（Reciprocal Rank Fusion，取 top 25）
    ↓
並行 Rerank（Ollama 0–5 分，分數 < 2 自動 fallback）
    ↓
相鄰 chunk 擴展（前後各 +1 chunk）
    ↓
答案生成（Ollama Streaming，僅根據文件內容回答）
```

### 四路檢索說明

| 路 | 方式 | 查詢 |
|----|------|------|
| 原始 keyword | SQL LIKE + 相關性排序 | 原始問題 |
| 重寫 keyword | SQL LIKE + 相關性排序 | Ollama 重寫後查詢 |
| 原始向量 | ChromaDB top 25 | 原始問題 embedding |
| 重寫向量 | ChromaDB top 25 | 重寫後查詢 embedding |

SQL keyword 搜尋取 TOP 200 後由 Python 重新加權評分，過濾 score=0 的無關結果。RRF 以排名而非原始分數整合四路結果，避免不同來源的分數尺度不一致。

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
# 在 SQL Server 建立資料庫後，依序執行：
#   schema.sql          ← 初始資料表
#   scripts/migration_v2.sql  ← 使用者群組權限 + 對話記錄
#   scripts/migration_v3.sql  ← 回答品質回饋欄位

# 4. 啟動伺服器
uv run uvicorn main:app --reload
```

### 密碼遷移（舊帳號）

若資料庫中存有明文密碼的舊帳號，執行以下腳本一鍵遷移為雜湊版本：

```bash
uv run python scripts/migrate_passwords.py
```

### 向量索引重建（補救用）

若 ChromaDB 與 SQL 資料不同步（例如 `chroma_db/` 被刪除），可手動重建全部向量索引：

```bash
uv run python scripts/index_chunks.py
```

---

## 專案目錄

```text
├─ main.py                        # FastAPI 進入點、SessionMiddleware、logging 設定
├─ .env.example                   # 設定檔範本（複製為 .env 後填入實際值）
├─ schema.sql                     # 初始資料庫資料表建立腳本
├─ logs/                          # 自動產生的 log 檔（app.log，自動 rotate）
├─ chroma_db/                     # ChromaDB 向量資料庫（本地持久化）
├─ core/
│  ├─ config.py                   # 從 .env 讀取所有設定
│  ├─ database.py                 # SQL Server 連線
│  └─ template.py                 # Jinja2 模板初始化
├─ repositories/
│  ├─ user_repository.py          # 使用者 CRUD
│  ├─ group_repository.py         # 文件群組 CRUD
│  ├─ document_repository.py      # 文件主檔 CRUD
│  ├─ chunk_repository.py         # chunk 查詢、相鄰擴展、關鍵字搜尋
│  ├─ vector_repository.py        # ChromaDB 操作（upsert、query、delete）
│  ├─ user_group_repository.py    # 使用者群組權限 CRUD
│  └─ chat_history_repository.py  # 對話記錄 CRUD + 統計查詢
├─ services/
│  ├─ auth_service.py             # 登入驗證、密碼雜湊與比對
│  ├─ group_service.py            # 群組業務邏輯
│  ├─ file_service.py             # PDF / TXT / DOCX 文字擷取
│  ├─ document_service.py         # 文字切 chunk（尊重句子邊界，保留 overlap）
│  ├─ embedding_service.py        # Ollama embedding + 並行向量索引建立
│  └─ rag_service.py              # 完整 RAG 流程（tokenize、四路檢索、RRF、rerank、生成）
├─ routers/
│  ├─ auth.py                     # 登入、登出、session 寫入
│  ├─ admin.py                    # 文件管理、群組管理、帳號管理、統計、Excel 匯出
│  └─ user.py                     # 問答、串流、回饋、對話記錄
├─ scripts/
│  ├─ schema.sql                  # 同根目錄 schema.sql（初始建表）
│  ├─ migration_v2.sql            # 新增 user_group_permissions、chat_history 資料表
│  ├─ migration_v3.sql            # chat_history 新增 feedback 欄位
│  ├─ index_chunks.py             # 手動全量重建向量索引（補救用）
│  └─ migrate_passwords.py        # 將舊明文密碼一鍵遷移為雜湊版本
├─ templates/
│  ├─ index.html                  # 登入頁
│  ├─ admin/
│  │  ├─ admin_dashboard.html     # Admin 功能目錄
│  │  ├─ admin_users.html         # 帳號管理
│  │  ├─ admin_user_groups.html   # 使用者群組權限指派
│  │  ├─ admin_groups.html        # 文件群組管理
│  │  ├─ admin_upload.html        # 文件上傳（含進度條）
│  │  ├─ admin_delete.html        # 文件刪除
│  │  └─ admin_stats.html         # 使用統計（直方圖 + Excel 匯出）
│  └─ user/
│     ├─ user_dashboard.html      # 問答頁（群組選擇、串流回答、回饋按鈕）
│     └─ user_history.html        # 個人對話記錄
└─ static/
   └─ style.css                   # 全站共用樣式
```
