# Local LLM Notebook

一個可在地端部署的文件問答系統，使用 FastAPI、Jinja2、MSSQL、ChromaDB 與 Ollama 建構。系統支援文件群組管理、文件上傳、文件 chunk 化儲存，以及依群組範圍限制的 RAG 問答流程，適合做為本地知識庫問答與 RAG 架構練習專案。

## 專案目標

本專案的核心目標是讓使用者能夠在指定文件群組內提問，並由本地模型根據系統內部文件內容回答問題，而不是直接依賴模型本身的通用知識。這種設計可提升回答的可追溯性，並降低模型直接胡亂補充外部知識的風險。

## 主要功能

- Admin / User 角色區分。
- 文件群組新增、刪除與管理。
- 文件上傳，自動切 chunk 並同步建立向量索引（ChromaDB），上傳後即可被向量搜尋到。
- 使用者依群組範圍提問。
- 中英文混合查詢自動切分（`dict怎麼用` → `['dict', '使用', '語法'...]`），避免整句當成一個搜尋詞。
- 使用 Ollama 進行查詢重寫與答案生成。
- 三路檢索融合：原始 keyword、重寫 keyword、向量搜尋（ChromaDB）。
- 使用 RRF（Reciprocal Rank Fusion）融合三路結果。
- 使用 Ollama rerank 對候選 chunk 做相關性評分，過濾雜訊後再生成答案。
- 顯示參考來源與 chunk debug 資訊，方便調整 RAG 表現。
- 統一 logging，輸出至終端機與 `logs/app.log`，方便除錯。

## 系統架構

### 前端

前端使用 Jinja2 模板渲染 HTML，主要提供：

- 文件群組選擇（雙欄拖拉介面）。
- 問題輸入。
- 系統回答顯示。
- 檢索來源與 chunk debug 顯示。

問答頁採用雙欄群組選擇模式，左側顯示所有群組，右側顯示已選群組，透過 hidden inputs 提交多個 `group_ids`，讓後端在重新渲染頁面時能保留使用者的群組選擇狀態。

### 後端

後端以 FastAPI 建立路由與服務邏輯，採分層設計：

```
routers → services → repositories → DB / ChromaDB / Ollama
```

- `routers`：接收 HTTP 請求，組合 service 呼叫，回填模板。
- `services`：業務邏輯，包含 RAG 流程、embedding、文件處理。
- `repositories`：資料存取，SQL Server 與 ChromaDB 操作。

### 資料庫

SQL Server 核心資料表：

| 資料表 | 說明 |
|--------|------|
| `document_groups` | 文件群組 |
| `documents` | 文件主檔與 metadata（含 SHA256 hash 做去重） |
| `document_chunks` | 切割後的 chunk（含 `chunk_index` 供相鄰擴展用） |
| `users` | 使用者帳號與角色 |

ChromaDB 向量資料庫（`chroma_db/`）：

- Collection `document_chunks`：儲存每個 chunk 的 embedding，metadata 含 `group_id` 供群組過濾。

### 模型層

本專案使用 Ollama 做本地推理，共三個用途：

| 用途 | 模型 | 說明 |
|------|------|------|
| Embedding | `mxbai-embed-large` | 將 chunk 與查詢向量化，供向量搜尋使用 |
| 查詢重寫 | `llama3:latest` | 把自然語言問題改寫成適合技術文件搜尋的關鍵詞 |
| 答案生成 | `llama3:latest` | 根據檢索到的 chunk 產生 grounded answer |
| Rerank 評分 | `llama3:latest` | 對候選 chunk 評 0–5 分，篩出真正能回答問題的片段 |

## 系統流程

### 1. 文件匯入

上傳時系統會：
1. 計算 SHA256 hash，如果已上傳過則跳過。
2. 解析文字內容（支援 PDF / TXT）。
3. 儲存文件 metadata 到 `documents`。
4. 切成 chunks（每塊 800 字，重疊 120 字）寫入 `document_chunks`。
5. **自動呼叫 Ollama embedding，將所有 chunk 寫入 ChromaDB**——不需要手動執行任何腳本，上傳後向量搜尋立刻可用。

### 2. 使用者提問

使用者在前端選定一個或多個群組後輸入問題，後端取得：

- 使用者名稱、問題文字、多個 `group_ids`。

### 3. 查詢 Tokenize

系統對查詢做智慧切分：

- 按空白與標點分割。
- 在中英文交界處自動切開（`dict怎麼用` → `['dict', '怎麼用']`）。
- 對長 CJK 片段產生 2-gram bigram（`怎麼使用` → 額外加 `['怎麼', '使用']`），避免整句當一個詞找不到任何 chunk。

### 4. 查詢重寫

Ollama 把原始問題改寫成更像技術文件的檢索詞，例如：

```
dict怎麼使用的 語法是甚麼 → Python dict 用法 dictionary 語法
```

### 5. 三路檢索

同時執行三路搜尋：

| 路 | 方式 | 說明 |
|----|------|------|
| 原始 keyword | SQL LIKE | 用原始問題的 token 做全文比對 |
| 重寫 keyword | SQL LIKE | 用重寫後查詢的 token 做全文比對 |
| 向量搜尋 | ChromaDB | 用問題 embedding 做語意相似度搜尋（top 25）|

SQL keyword 搜尋會先對 `title`、`filename`、`chunk_text` 加權排序後取 TOP 200，再由 Python 重新評分，過濾掉 score=0 的無關結果。

### 6. RRF 結果融合

三路結果用 RRF（Reciprocal Rank Fusion）融合。RRF 以排名而非原始分數整合，適合多來源結果合併。融合後取 top 15。

### 7. Rerank

對融合後的 top 3 候選 chunk，讓 Ollama 各評一個 0–5 的相關性分數，再按分數重排。這個步驟確保最後進入 context 的 chunk 是真正能回答問題的片段，而非只是碰巧含有關鍵字。

### 8. 相鄰 chunk 擴展

對 rerank 後的 top 5 chunk，根據 `document_id` 與 `chunk_index` 抓取前後各一個 chunk，補足上下文，避免答案恰好被切在 chunk 邊界。

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
# 安裝依賴
uv sync

# 啟動伺服器
uv run uvicorn main:app --reload
```

> 首次啟動前請確認 SQL Server 已建立 `local_llm_notebook` 資料庫，並建立所需資料表（`document_groups`, `documents`, `document_chunks`, `users`）。

## 專案目錄

```text
├─ main.py                  # FastAPI 進入點、logging 設定
├─ logs/                    # 自動產生的 log 檔（app.log）
├─ chroma_db/               # ChromaDB 向量資料庫（本地持久化）
├─ core/
│  ├─ database.py           # SQL Server 連線
│  └─ template.py           # Jinja2 模板初始化
├─ repositories/
│  ├─ group_repository.py
│  ├─ document_repository.py
│  ├─ chunk_repository.py   # 含相鄰 chunk 查詢與依文件 ID 查詢
│  └─ vector_repository.py  # ChromaDB 操作
├─ services/
│  ├─ auth_service.py
│  ├─ file_service.py       # PDF / TXT 文字擷取
│  ├─ document_service.py   # 文字切 chunk
│  ├─ embedding_service.py  # Ollama embedding + 自動向量索引
│  └─ rag_service.py        # 完整 RAG 流程（tokenize、搜尋、融合、rerank、生成）
├─ routers/
│  ├─ auth.py
│  ├─ admin.py              # 上傳、群組管理、刪除
│  └─ user.py               # 提問與 RAG 流程觸發
├─ scripts/
│  └─ index_chunks.py       # 手動全量重建向量索引（補救用）
├─ templates/
│  ├─ admin/
│  └─ user/
└─ static/
   └─ style.css
```
