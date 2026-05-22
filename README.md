# Local LLM Notebook

一個可在地端部署的文件問答系統，使用 FastAPI、Jinja2、MSSQL 與 Ollama 建構。系統支援文件群組管理、文件上傳、文件 chunk 化儲存，以及依群組範圍限制的 RAG 問答流程，適合做為本地知識庫問答與 RAG 架構練習專案。

## 專案目標

本專案的核心目標是讓使用者能夠在指定文件群組內提問，並由本地模型根據系統內部文件內容回答問題，而不是直接依賴模型本身的通用知識。這種設計可提升回答的可追溯性，並降低模型直接胡亂補充外部知識的風險。

## 主要功能

- Admin / User 角色區分。
- 文件群組新增、刪除與管理。
- 文件上傳與文件 metadata 儲存。
- 將文件內容切成 chunks 後寫入 `document_chunks`。
- 使用者依群組範圍提問。
- 使用 Ollama 進行查詢重寫與答案生成。
- 以原始查詢與重寫查詢做雙路檢索。
- 使用 RRF（Reciprocal Rank Fusion）融合檢索結果。
- 顯示參考來源與 chunks debug 資訊，方便調整 RAG 表現。

## 系統架構

### 前端

前端使用 Jinja2 模板渲染 HTML，主要提供：

- 文件群組選擇。
- 問題輸入。
- 系統回答顯示。
- 檢索來源與 chunks debug 顯示。

目前問答頁採用雙欄群組選擇模式，左側顯示所有群組，右側顯示已選群組，並透過 hidden inputs 提交多個 `group_ids`，讓後端能在重新渲染頁面時保留使用者的群組選擇狀態。

### 後端

後端以 FastAPI 建立路由與服務邏輯，主要負責：

- 使用者與管理者頁面路由。
- 表單資料接收。
- 文件匯入流程。
- RAG service 呼叫。
- Jinja 模板回填與畫面渲染。

FastAPI 可以透過 `request.form()` 與 `getlist()` 處理同名欄位多值提交，因此適合目前的多群組選擇設計。

### 資料庫

目前資料庫的核心結構可分為：

- `documents`：文件主檔與 metadata。
- `document_groups`：文件群組。
- `document_chunks`：切割後的 chunk 內容。

chunk 資料通常會包含 `document_id`、`chunk_index` 與 `chunk_text`，供檢索、rerank 與相鄰 chunk 擴展使用。這種 chunk-based 設計是 RAG 系統常見基礎做法。

### 模型層

本專案使用 Ollama 做本地推理，現階段主要有兩個用途：

- **查詢重寫器**：把使用者問題改寫成比較適合技術文件搜尋的 query。

- **答案生成器**：根據檢索到的 chunks 產生 grounded answer。

這也就是目前系統裡會看到兩個 prompt 的原因：兩個 prompt 服務的是不同任務，而不是重複做同一件事。

## 系統流程

### 1. 文件匯入

當文件被上傳後，系統會先保存文件 metadata，再解析文字內容並切成多個 chunks，最後將 chunks 寫入 `document_chunks`。這讓系統不必在問答時每次重新解析整份文件，而是直接用 chunk 為單位查詢。

### 2. 使用者提問

使用者在前端頁面選定一個或多個群組後輸入問題，後端會取得：

- 使用者名稱。
- 問題文字。
- 多個 `group_ids`。

這些資訊會作為整個檢索範圍與回答流程的基礎。

### 3. 查詢重寫

系統會先保留原始問題，再用 Ollama 把問題改寫成更像教材或技術文件會使用的檢索詞。查詢重寫的目的，是補足同義詞、技術名詞與較自然的搜尋型表述，以提高召回率。

### 4. 雙路檢索

系統會同時用：

- 原始問題
- 重寫後查詢

各做一次 chunk 檢索。現階段檢索仍以 keyword matching 為主，通常會根據 `title`、`filename` 與 `chunk_text` 的命中情況進行加權評分。
### 5. 結果融合

兩路檢索結果會再使用 RRF 融合。RRF 能用排名而不是原始分數來整合不同檢索來源，因此很適合原查詢與重寫查詢這種多來源結果合併場景。

### 6. rerank 與過濾

多文件情境下，排在前面的 chunks 不一定真的能回答問題，因此系統可再加入第二階段 relevance 檢查或 rerank。這種 two-stage retrieval 的做法可避免只命中關鍵字、但資訊不足的 chunks 進入最終 context。

### 7. 相鄰 chunk 擴展

對高相關 chunk，系統可以再根據 `document_id` 與 `chunk_index` 抓取前後 chunk，補足上下文，避免答案剛好被切在 chunk 邊界。這對長文件尤其重要。

### 8. 答案生成

最後，系統將整理後的 chunks 丟給 Ollama，要求模型只能根據提供的文件內容回答，若資訊不足則明確表示無法確定。這種 grounded answer 設計是 RAG 系統降低 hallucination 的關鍵方法。

## 專案目錄建議

以下為建議性的目錄結構，實際檔名可依專案調整：

```text
app/
├─ main.py
├─ core/
│  ├─ database.py
│  └─ template.py
├─ repositories/
│  ├─ group_repository.py
│  ├─ document_repository.py
│  └─ chunk_repository.py
├─ routers/
│  ├─ admin.py
│  └─ user.py
├─ services/
│  ├─ file_service.py
│  └─ rag_service.py
├─ templates/
│  ├─ admin/
│  └─ user/
└─ static/
   └─ style.css
```

這種分層方式可以把資料存取、商業邏輯、頁面路由與模板顯示清楚分離，後續擴充也比較容易。

