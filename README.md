# Local LLM Notebook

一個可在地端部署的文件問答系統，使用 FastAPI、Jinja2、MSSQL 與 Ollama 建構。系統支援文件群組管理、文件上傳、文件 chunk 化儲存，以及依群組範圍限制的 RAG 問答流程，適合做為本地知識庫問答與 RAG 架構練習專案。[cite:1359][cite:1319]

## 專案目標

本專案的核心目標是讓使用者能夠在指定文件群組內提問，並由本地模型根據系統內部文件內容回答問題，而不是直接依賴模型本身的通用知識。這種設計可提升回答的可追溯性，並降低模型直接胡亂補充外部知識的風險。[cite:1354][cite:1359]

## 主要功能

- Admin / User 角色區分。
- 文件群組新增、刪除與管理。
- 文件上傳與文件 metadata 儲存。
- 將文件內容切成 chunks 後寫入 `document_chunks`。
- 使用者依群組範圍提問。
- 使用 Ollama 進行查詢重寫與答案生成。
- 以原始查詢與重寫查詢做雙路檢索。
- 使用 RRF（Reciprocal Rank Fusion）融合檢索結果。
- 顯示參考來源與 chunks debug 資訊，方便調整 RAG 表現。[cite:1294][cite:1258][cite:1298]

## 系統架構

### 前端

前端使用 Jinja2 模板渲染 HTML，主要提供：

- 文件群組選擇。
- 問題輸入。
- 系統回答顯示。
- 檢索來源與 chunks debug 顯示。

目前問答頁採用雙欄群組選擇模式，左側顯示所有群組，右側顯示已選群組，並透過 hidden inputs 提交多個 `group_ids`，讓後端能在重新渲染頁面時保留使用者的群組選擇狀態。[cite:1329][cite:1336][cite:1321]

### 後端

後端以 FastAPI 建立路由與服務邏輯，主要負責：

- 使用者與管理者頁面路由。
- 表單資料接收。
- 文件匯入流程。
- RAG service 呼叫。
- Jinja 模板回填與畫面渲染。

FastAPI 可以透過 `request.form()` 與 `getlist()` 處理同名欄位多值提交，因此適合目前的多群組選擇設計。[cite:1336][cite:1338][cite:1304]

### 資料庫

目前資料庫的核心結構可分為：

- `documents`：文件主檔與 metadata。
- `document_groups`：文件群組。
- `document_chunks`：切割後的 chunk 內容。

chunk 資料通常會包含 `document_id`、`chunk_index` 與 `chunk_text`，供檢索、rerank 與相鄰 chunk 擴展使用。這種 chunk-based 設計是 RAG 系統常見基礎做法。[cite:1319][cite:1381]

### 模型層

本專案使用 Ollama 做本地推理，現階段主要有兩個用途：

- **查詢重寫器**：把使用者問題改寫成比較適合技術文件搜尋的 query。[cite:1294][cite:1300]
- **答案生成器**：根據檢索到的 chunks 產生 grounded answer。[cite:1352][cite:1355]

這也就是目前系統裡會看到兩個 prompt 的原因：兩個 prompt 服務的是不同任務，而不是重複做同一件事。[cite:1247][cite:1359]

## 系統流程

### 1. 文件匯入

當文件被上傳後，系統會先保存文件 metadata，再解析文字內容並切成多個 chunks，最後將 chunks 寫入 `document_chunks`。這讓系統不必在問答時每次重新解析整份文件，而是直接用 chunk 為單位查詢。[cite:1319][cite:1381]

### 2. 使用者提問

使用者在前端頁面選定一個或多個群組後輸入問題，後端會取得：

- 使用者名稱。
- 問題文字。
- 多個 `group_ids`。

這些資訊會作為整個檢索範圍與回答流程的基礎。[cite:1336][cite:1338]

### 3. 查詢重寫

系統會先保留原始問題，再用 Ollama 把問題改寫成更像教材或技術文件會使用的檢索詞。查詢重寫的目的，是補足同義詞、技術名詞與較自然的搜尋型表述，以提高召回率。[cite:1294][cite:1353][cite:1300]

### 4. 雙路檢索

系統會同時用：

- 原始問題
- 重寫後查詢

各做一次 chunk 檢索。現階段檢索仍以 keyword matching 為主，通常會根據 `title`、`filename` 與 `chunk_text` 的命中情況進行加權評分。[cite:1249][cite:1319]

### 5. 結果融合

兩路檢索結果會再使用 RRF 融合。RRF 能用排名而不是原始分數來整合不同檢索來源，因此很適合原查詢與重寫查詢這種多來源結果合併場景。[cite:1258][cite:1284]

### 6. rerank 與過濾

多文件情境下，排在前面的 chunks 不一定真的能回答問題，因此系統可再加入第二階段 relevance 檢查或 rerank。這種 two-stage retrieval 的做法可避免只命中關鍵字、但資訊不足的 chunks 進入最終 context。[cite:1389][cite:1392][cite:1397]

### 7. 相鄰 chunk 擴展

對高相關 chunk，系統可以再根據 `document_id` 與 `chunk_index` 抓取前後 chunk，補足上下文，避免答案剛好被切在 chunk 邊界。這對長文件尤其重要。[cite:1262][cite:1259][cite:1378]

### 8. 答案生成

最後，系統將整理後的 chunks 丟給 Ollama，要求模型只能根據提供的文件內容回答，若資訊不足則明確表示無法確定。這種 grounded answer 設計是 RAG 系統降低 hallucination 的關鍵方法。[cite:1352][cite:1355][cite:1354]

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

這種分層方式可以把資料存取、商業邏輯、頁面路由與模板顯示清楚分離，後續擴充也比較容易。[cite:1319]

## 安裝與啟動

### 1. 安裝 SQL Server ODBC Driver

若在 Windows 環境使用 MSSQL 與 `pyodbc`，常見做法是先安裝 **Microsoft ODBC Driver 18 for SQL Server**。[cite:22][cite:25]

```powershell
winget install -e --id Microsoft.msodbcsql.18
```

### 2. 建立虛擬環境與安裝套件

```bash
uv venv --python 3.11
.venv\Scripts\activate
uv add fastapi uvicorn sqlalchemy jinja2 python-multipart pyodbc requests
```

若有直接使用 `requests` 呼叫 Ollama API，請確保 `requests` 已安裝。

### 3. 設定 MSSQL 連線

```powershell
$env:MSSQL_SERVER="localhost"
$env:MSSQL_PORT="1433"
$env:MSSQL_DATABASE="local_llm_notebook"
$env:MSSQL_USERNAME="sa"
$env:MSSQL_PASSWORD="YourStrong!Passw0rd"
$env:MSSQL_DRIVER="ODBC Driver 18 for SQL Server"
$env:MSSQL_TRUST_CERT="yes"
```

SQLAlchemy 使用 SQL Server 時，通常可透過 `mssql+pyodbc` 連線。[cite:20][cite:21][cite:23]

### 4. 啟動 Ollama

本專案假設 Ollama 已安裝並啟動，本地 API 預設使用：

```text
http://localhost:11434/api/generate
```

模型名稱目前預設為：

```text
llama3:latest
```

請先確認模型已下載完成且可正常使用。[cite:1315]

### 5. 啟動 FastAPI

```bash
uv run uvicorn app.main:app --reload
```

啟動後可使用：

- 首頁：http://127.0.0.1:8000/
- API 文件：http://127.0.0.1:8000/docs

## 預設帳號

- admin / admin123
- user / user123

## 目前已知問題

### 單一文件正常，多文件容易失準

目前最明顯的問題是：當群組內只有一份文件時，系統通常能正常找到 relevant chunks；但一旦同群組內有多份文件，真正該被命中的 chunk 容易被其他 chunks 擠掉，導致 top-k 沒留下真正有答案的內容。這是典型的 multi-document retrieval failure。[cite:1361][cite:1412][cite:1416]

### 單一文件可能壟斷結果

若某份文件被切成大量相似 chunks，前幾名結果可能幾乎都來自同一份文件，進一步壓縮其他文件進入 context 的機會。[cite:1365][cite:1368]

### 候選池與速度的取捨

若候選池拉大，通常能提升多文件召回率，但若每個候選 chunk 都要再進行 LLM rerank，loading 時間也會明顯增加。因此較合理的做法是先用便宜排序篩到前一小批，再只對這批做 rerank。[cite:1389][cite:1394][cite:1412]

## 優化方向

### 短期

- 先擴大初步候選池，再做 rerank。[cite:1389][cite:1394]
- 對 chunk 做 relevance scoring，避免廢話 chunk 進入 context。[cite:1392][cite:1397]
- 改善多文件下的排序與 document-level diversification。[cite:1365][cite:1368]
- 更清楚地顯示 rewritten query、score 與 chunks debug 資訊。[cite:1293][cite:1298]

### 中期

- 將 chunks 向量化。[cite:1315]
- 導入 hybrid search（keyword + vector）。[cite:1312][cite:1317]
- 視文件型態調整 chunking 策略與 larger-parent retrieval。[cite:1378][cite:1381]

## 是否需要重新匯入文件

若目前只是調整以下內容，通常不需要重新匯入文件：

- query rewrite prompt。
- merge / RRF 排序邏輯。
- relevance scoring。
- rerank。
- 相鄰 chunk 擴展。

因為這些變更只影響查詢與排序流程，不會改變既有 chunk 資料。[cite:1389][cite:1394][cite:1294]

通常需要重新匯入或重建索引的情況包括：

- 文件內容更新。
- chunk 切法改變。
- 新增 embeddings / 向量索引。[cite:1404][cite:1408][cite:1405]

## 常見排查方向

### 問題 1：為什麼回答一直說無法確定

可能原因：

- 沒有檢索到真正相關的 chunk。
- prompt 設定過於保守。
- chunk 被切得太碎，缺乏上下文。[cite:1412][cite:1381]

### 問題 2：為什麼只命中第一份文件

可能原因：

- 排名前段被某份文件壟斷。
- 候選池太小。
- 多文件情境下答案 chunk 被擠掉。[cite:1365][cite:1361]

### 問題 3：為什麼群組每次都要重選

常見原因是前端送出多個 `group_ids` 後，後端沒有用 `getlist()` 正確取回，或沒有把 `selected_group_ids` 傳回模板重渲染。[cite:1336][cite:1321]

## 專案定位

這個專案目前最適合被視為一個可持續擴充的本地 RAG 實驗與教學專案。它已具備完整的文件匯入、群組管理、chunk 檢索與 Ollama grounded answer 流程，後續可以逐步升級為更完整的 hybrid retrieval 系統。[cite:1319][cite:1355][cite:1312]
EOF
cp ./output/local-llm-notebook-app/README.md ./output/updated_README_complete.md
ls -l ./output/local-llm-notebook-app/README.md ./output/updated_README_complete.md
head -n 40 ./output/local-llm-notebook-app/README.md
-rw-r--r-- 1 user user 10212 May 22 12:03 ./output/local-llm-notebook-app/README.md
-rw-r--r-- 1 user user 10212 May 22 12:03 ./output/updated_README_complete.md
# Local LLM Notebook

一個可在地端部署的文件問答系統，使用 FastAPI、Jinja2、MSSQL 與 Ollama 建構。系統支援文件群組管理、文件上傳、文件 chunk 化儲存，以及依群組範圍限制的 RAG 問答流程，適合做為本地知識庫問答與 RAG 架構練習專案。[cite:1359][cite:1319]

## 專案目標

本專案的核心目標是讓使用者能夠在指定文件群組內提問，並由本地模型根據系統內部文件內容回答問題，而不是直接依賴模型本身的通用知識。這種設計可提升回答的可追溯性，並降低模型直接胡亂補充外部知識的風險。[cite:1354][cite:1359]

## 主要功能

- Admin / User 角色區分。
- 文件群組新增、刪除與管理。
- 文件上傳與文件 metadata 儲存。
- 將文件內容切成 chunks 後寫入 `document_chunks`。
- 使用者依群組範圍提問。
- 使用 Ollama 進行查詢重寫與答案生成。
- 以原始查詢與重寫查詢做雙路檢索。
- 使用 RRF（Reciprocal Rank Fusion）融合檢索結果。
- 顯示參考來源與 chunks debug 資訊，方便調整 RAG 表現。[cite:1294][cite:1258][cite:1298]

## 系統架構

### 前端

前端使用 Jinja2 模板渲染 HTML，主要提供：

- 文件群組選擇。
- 問題輸入。
- 系統回答顯示。
- 檢索來源與 chunks debug 顯示。

目前問答頁採用雙欄群組選擇模式，左側顯示所有群組，右側顯示已選群組，並透過 hidden inputs 提交多個 `group_ids`，讓後端能在重新渲染頁面時保留使用者的群組選擇狀態。[cite:1329][cite:1336][cite:1321]

### 後端

後端以 FastAPI 建立路由與服務邏輯，主要負責：

- 使用者與管理者頁面路由。
- 表單資料接收。
- 文件匯入流程。