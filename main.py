from pathlib import Path
import pyodbc
from fastapi import FastAPI, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from io import BytesIO
from pypdf import PdfReader
import requests
import re

app = FastAPI()

BASE_DIR = Path(__file__).resolve().parent

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

def tokenize_query(query: str):
    query = (query or "").strip()
    if not query:
        return []

    tokens = re.split(r"[\s,，。！？；：/\\|]+", query)
    tokens = [t.strip() for t in tokens if t.strip()]
    return tokens[:8]

def get_connection():
    conn = pyodbc.connect(
        "DRIVER={ODBC Driver 18 for SQL Server};"
        "SERVER=localhost\\SQLEXPRESS;"
        "DATABASE=local_llm_notebook;"
        "Trusted_Connection=yes;"
        "TrustServerCertificate=yes;"
    )
    return conn


def get_groups():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, description FROM document_groups ORDER BY id")
    rows = cursor.fetchall()

    groups = []
    for row in rows:
        groups.append({
            "id": row.id,
            "name": row.name,
            "description": row.description
        })

    cursor.close()
    conn.close()
    return groups


def get_documents(group_id=None):
    conn = get_connection()
    cursor = conn.cursor()

    if group_id:
        cursor.execute("""
            SELECT d.id, d.title, d.filename, g.name AS group_name
            FROM documents d
            INNER JOIN document_groups g ON d.group_id = g.id
            WHERE d.group_id = ?
            ORDER BY d.id DESC
        """, group_id)
    else:
        cursor.execute("""
            SELECT d.id, d.title, d.filename, g.name AS group_name
            FROM documents d
            INNER JOIN document_groups g ON d.group_id = g.id
            ORDER BY d.id DESC
        """)

    rows = cursor.fetchall()

    documents = []
    for row in rows:
        documents.append({
            "id": row.id,
            "title": row.title,
            "filename": row.filename,
            "group_name": row.group_name
        })

    cursor.close()
    conn.close()
    return documents


@app.get("/", response_class=HTMLResponse)
def home(request: Request, error: str = None):
    message = "請登入 Local LLM Notebook"
    if error:
        message = "登入失敗，帳號或密碼錯誤"

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"message": message}
    )


@app.post("/login")
def login(username: str = Form(...), password: str = Form(...)):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT username, role FROM users WHERE username = ? AND password = ?",
        username,
        password
    )
    user = cursor.fetchone()

    cursor.close()
    conn.close()

    if user:
        if user.role == "admin":
            return RedirectResponse(
                url=f"/admin/dashboard?username={user.username}",
                status_code=303
            )
        return RedirectResponse(
            url=f"/user/dashboard?username={user.username}",
            status_code=303
        )

    return RedirectResponse(url="/?error=1", status_code=303)


@app.get("/admin/dashboard", response_class=HTMLResponse)
def admin_dashboard(request: Request, username: str):
    return templates.TemplateResponse(
        request=request,
        name="admin/admin_dashboard.html",
        context={
            "username": username,
            "message": "Admin 管理目錄"
        }
    )


@app.get("/admin/upload", response_class=HTMLResponse)
def admin_upload_page(request: Request, username: str):
    groups = get_groups()
    documents = get_documents()
    return templates.TemplateResponse(
        request=request,
        name="admin/admin_upload.html",
        context={
            "username": username,
            "groups": groups,
            "documents": documents,
            "message": "上傳文件"
        }
    )


@app.get("/admin/groups", response_class=HTMLResponse)
def admin_groups_page(request: Request, username: str):
    groups = get_groups()
    return templates.TemplateResponse(
        request=request,
        name="admin/admin_groups.html",
        context={
            "username": username,
            "groups": groups,
            "message": "新建群組"
        }
    )


@app.get("/user/dashboard", response_class=HTMLResponse)
def user_dashboard(request: Request, username: str):
    return templates.TemplateResponse(
        request=request,
        name="user/user_dashboard.html",
        context={
            "username": username,
            "message": "User 提問頁",
            "question": "",
            "results": [],
            "answer": "請輸入問題後送出。"
        }
    )

@app.post("/ask", response_class=HTMLResponse)
def ask_question(
    request: Request,
    username: str = Form(...),
    question: str = Form(...)
):
    results = search_document_chunks(question)
    answer = generate_answer_with_ollama(question, results)

    return templates.TemplateResponse(
        request=request,
        name="user/user_dashboard.html",
        context={
            "username": username,
            "message": "User 提問頁",
            "question": question,
            "results": results,
            "answer": answer
        }
    )

@app.post("/add-group", response_class=HTMLResponse)
def add_group(
    request: Request,
    username: str = Form(...),
    group_name: str = Form(...),
    group_description: str = Form(...)
):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT role FROM users WHERE username = ?", username)
    user = cursor.fetchone()

    if not user or user.role != "admin":
        cursor.close()
        conn.close()
        return RedirectResponse(url="/", status_code=303)

    cursor.execute(
        "INSERT INTO document_groups (name, description) VALUES (?, ?)",
        group_name,
        group_description
    )
    conn.commit()

    cursor.close()
    conn.close()

    groups = get_groups()
    return templates.TemplateResponse(
        request=request,
        name="admin/admin_groups.html",
        context={
            "message": f"群組新增成功：{group_name}",
            "username": username,
            "groups": groups
        }
    )


@app.post("/upload-document", response_class=HTMLResponse)
async def upload_document(
    request: Request,
    username: str = Form(...),
    title: str = Form(...),
    group_id: int = Form(...),
    file: UploadFile = File(...)
):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT role FROM users WHERE username = ?", username)
    user = cursor.fetchone()

    if not user or user.role != "admin":
        cursor.close()
        conn.close()
        return templates.TemplateResponse(
            request=request,
            name="admin/admin_upload.html",
            context={
                "message": "你沒有權限上傳文件",
                "username": username,
                "groups": [],
                "documents": []
            }
        )

    content_bytes = await file.read()
    content_text = extract_text_from_file(file.filename, content_bytes)

    if content_text is None:
        cursor.close()
        conn.close()
        return templates.TemplateResponse(
            request=request,
            name="admin/admin_upload.html",
            context={
                "message": "目前只支援上傳 txt 與 pdf 檔案",
                "username": username,
                "groups": get_groups(),
                "documents": get_documents()
            }
        )

    if not content_text.strip():
        cursor.close()
        conn.close()
        return templates.TemplateResponse(
        request=request,
            name="admin/admin_upload.html",
            context={
                "message": "檔案讀取成功，但沒有擷取到文字內容",
                "username": username,
                "groups": get_groups(),
                "documents": get_documents()
            }
        )

    cursor.execute(
        "INSERT INTO documents (title, filename, content, group_id) VALUES (?, ?, ?, ?)",
        title,
        file.filename,
        content_text,
        group_id
    )
    conn.commit()

    cursor.execute("SELECT TOP 1 id FROM documents WHERE filename = ? ORDER BY id DESC", file.filename)
    row = cursor.fetchone()
    document_id = row[0]

    cursor.close()
    conn.close()

    chunk_count = insert_document_chunks(document_id, content_text)

    groups = get_groups()
    documents = get_documents()
    return templates.TemplateResponse(
        request=request,
        name="admin/admin_upload.html",
        context={
            "message": f"文件上傳成功：{file.filename}",
            "username": username,
            "groups": groups,
            "documents": documents
        }
    )

@app.get("/admin/delete", response_class=HTMLResponse)
def admin_delete_page(request: Request, username: str, group_id: int = None):
    groups = get_groups()
    documents = get_documents(group_id)

    return templates.TemplateResponse(
        request=request,
        name="admin/admin_delete.html",
        context={
            "username": username,
            "groups": groups,
            "documents": documents,
            "selected_group_id": group_id,
            "message": "刪除文件"
        }
    )

@app.post("/delete-document")
def delete_document(
    request: Request,
    username: str = Form(...),
    document_id: int = Form(...),
    group_id: int = Form(...)
):
    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(
            "DELETE FROM document_chunks WHERE document_id = ?",
            document_id
        )

        cursor.execute(
            "DELETE FROM documents WHERE id = ?",
            document_id
        )

        conn.commit()

    except Exception as e:
        conn.rollback()
        print(f"刪除文件失敗：{e}")

    finally:
        cursor.close()
        conn.close()

    return RedirectResponse(
        url=f"/admin/delete?username={username}&group_id={group_id}",
        status_code=303
    )

def search_documents(question: str):
    conn = get_connection()
    cursor = conn.cursor()

    keyword = f"%{question}%"
    cursor.execute(
        """
        SELECT TOP 5 d.id, d.title, d.filename, d.content, g.name AS group_name
        FROM documents d
        INNER JOIN document_groups g ON d.group_id = g.id
        WHERE d.content LIKE ? OR d.title LIKE ?
        ORDER BY d.id DESC
        """,
        keyword,
        keyword,
    )
    rows = cursor.fetchall()

    results = []
    for row in rows:
        snippet = row.content[:300] if row.content else ""
        results.append({
            "id": row.id,
            "title": row.title,
            "filename": row.filename,
            "group_name": row.group_name,
            "snippet": snippet
        })

    cursor.close()
    conn.close()
    return results

def extract_text_from_file(file_name: str, content_bytes: bytes):
    lower_name = file_name.lower()

    if lower_name.endswith(".txt"):
        return content_bytes.decode("utf-8", errors="ignore")

    if lower_name.endswith(".pdf"):
        pdf_stream = BytesIO(content_bytes)
        reader = PdfReader(pdf_stream)

        text = ""
        for page in reader.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"

        return text

    return None

@app.post("/delete-group", response_class=HTMLResponse)
def delete_group(
    request: Request,
    username: str = Form(...),
    group_id: int = Form(...)
):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT role FROM users WHERE username = ?", username)
    user = cursor.fetchone()

    if not user or user.role != "admin":
        cursor.close()
        conn.close()
        return templates.TemplateResponse(
            request=request,
            name="admin/admin_groups.html",
            context={
                "message": "你沒有權限刪除群組",
                "username": username,
                "groups": get_groups()
            }
        )

    cursor.execute("SELECT COUNT(*) FROM documents WHERE group_id = ?", group_id)
    doc_count = cursor.fetchone()[0]

    if doc_count > 0:
        cursor.close()
        conn.close()
        return templates.TemplateResponse(
            request=request,
            name="admin/admin_groups.html",
            context={
                "message": "此群組底下仍有文件，請先刪除文件後再刪除群組",
                "username": username,
                "groups": get_groups()
            }
        )

    cursor.execute("DELETE FROM user_group_permissions WHERE group_id = ?", group_id)
    cursor.execute("DELETE FROM document_groups WHERE id = ?", group_id)
    conn.commit()

    cursor.close()
    conn.close()

    return templates.TemplateResponse(
        request=request,
        name="admin/admin_groups.html",
        context={
            "message": f"群組刪除成功，ID = {group_id}",
            "username": username,
            "groups": get_groups()
        }
    )

def search_documents(question: str):
    conn = get_connection()
    cursor = conn.cursor()

    keyword = f"%{question}%"
    cursor.execute(
        """
        SELECT TOP 5 d.id, d.title, d.filename, d.content, g.name AS group_name
        FROM documents d
        INNER JOIN document_groups g ON d.group_id = g.id
        WHERE d.content LIKE ? OR d.title LIKE ?
        ORDER BY d.id DESC
        """,
        keyword,
        keyword,
    )
    rows = cursor.fetchall()

    results = []
    for row in rows:
        snippet = row.content[:300] if row.content else ""
        results.append({
            "id": row.id,
            "title": row.title,
            "filename": row.filename,
            "group_name": row.group_name,
            "snippet": snippet
        })

    cursor.close()
    conn.close()
    return results


@app.get("/user/dashboard", response_class=HTMLResponse)
def user_dashboard(request: Request, username: str):
    return templates.TemplateResponse(
        request=request,
        name="user/user_dashboard.html",
        context={
            "username": username,
            "message": "User 提問頁",
            "question": "",
            "results": [],
            "answer": "請輸入問題後送出。"
        }
    )


@app.post("/ask", response_class=HTMLResponse)
def ask_question(
    request: Request,
    username: str = Form(...),
    question: str = Form(...)
):
    rewritten_query = rewrite_query_with_ollama(question)

    results_original = search_document_chunks(question)
    results_rewritten = search_document_chunks(rewritten_query)
    results = merge_results(results_original, results_rewritten)

    answer = generate_answer_with_ollama(question, results)

    return templates.TemplateResponse(
        request=request,
        name="user/user_dashboard.html",
        context={
            "username": username,
            "message": "User 提問頁",
            "question": question,
            "results": results,
            "answer": answer,
            "rewritten_query": rewritten_query
        }
    )

def split_text_into_chunks(text: str, chunk_size: int = 800, overlap: int = 120):
    text = (text or "").strip()
    if not text:
        return []

    chunks = []
    start = 0
    text_length = len(text)

    while start < text_length:
        end = start + chunk_size
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= text_length:
            break
        start += chunk_size - overlap

    return chunks


def insert_document_chunks(document_id: int, text: str):
    chunks = split_text_into_chunks(text)
    if not chunks:
        return 0

    conn = get_connection()
    cursor = conn.cursor()

    for idx, chunk_text in enumerate(chunks, start=1):
        cursor.execute(
            "INSERT INTO document_chunks (document_id, chunk_index, chunk_text) VALUES (?, ?, ?)",
            document_id,
            idx,
            chunk_text,
        )

    conn.commit()
    cursor.close()
    conn.close()
    return len(chunks)


def search_document_chunks(query: str):
    conn = get_connection()
    cursor = conn.cursor()

    tokens = tokenize_query(query)

    if not tokens:
        cursor.close()
        conn.close()
        return []

    where_parts = []
    params = []

    for token in tokens:
        where_parts.append("(c.chunk_text LIKE ? OR d.title LIKE ?)")
        keyword = f"%{token}%"
        params.extend([keyword, keyword])

    where_sql = " OR ".join(where_parts)

    sql = f"""
        SELECT TOP 15
            c.id,
            c.chunk_index,
            c.chunk_text,
            d.title,
            d.filename,
            g.name AS group_name
        FROM document_chunks c
        INNER JOIN documents d ON c.document_id = d.id
        INNER JOIN document_groups g ON d.group_id = g.id
        WHERE {where_sql}
    """

    cursor.execute(sql, params)
    rows = cursor.fetchall()

    results = []
    seen_chunk_ids = set()

    for row in rows:
        if row.id in seen_chunk_ids:
            continue
        seen_chunk_ids.add(row.id)

        full_text = row.chunk_text or ""
        text_lower = full_text.lower()
        title_lower = (row.title or "").lower()

        score = 0
        matched_tokens = []

        for token in tokens:
            token_lower = token.lower()
            if token_lower in title_lower:
                score += 3
                matched_tokens.append(token)
            elif token_lower in text_lower:
                score += 1
                matched_tokens.append(token)

        snippet = full_text[:300]

        results.append({
            "chunk_id": row.id,
            "chunk_index": row.chunk_index,
            "title": row.title,
            "filename": row.filename,
            "group_name": row.group_name,
            "chunk_text": full_text,
            "snippet": snippet,
            "score": score,
            "matched_tokens": matched_tokens
        })

    results.sort(key=lambda x: (x["score"], -x["chunk_index"]), reverse=True)

    cursor.close()
    conn.close()
    return results[:5]

def rewrite_query_with_ollama(question: str, model_name: str = "llama3:latest"):
    prompt = f"""
你是一個文件檢索查詢重寫器。
請把使用者問題改寫成適合拿來搜尋文件內容的簡短查詢。

規則：
1. 保留原意。
2. 保留產品名、功能名、費用、期限、保固、退款、數字等關鍵資訊。
3. 移除贅字與聊天語氣。
4. 輸出 1 行即可，不要解釋，不要加前綴。

使用者問題：
{question}
""".strip()

    try:
        response = requests.post(
            "http://localhost:11434/api/generate",
            json={
                "model": model_name,
                "prompt": prompt,
                "stream": False
            },
            timeout=60
        )
        response.raise_for_status()
        data = response.json()
        rewritten = data.get("response", "").strip()
        return rewritten if rewritten else question
    except Exception:
        return question
    
def merge_results(*result_lists):
    merged = []
    seen_chunk_ids = set()

    for result_list in result_lists:
        for item in result_list:
            chunk_id = item.get("chunk_id")
            if chunk_id not in seen_chunk_ids:
                seen_chunk_ids.add(chunk_id)
                merged.append(item)

    return merged[:5]

def generate_answer_with_ollama(question: str, results: list, model_name: str = "llama3:latest"):
    if not results:
        return "根據目前提供的文件內容，無法確定答案。"

    context_parts = []
    for item in results[:3]:
        context_parts.append(
            f"文件標題：{item['title']}\n"
            f"檔名：{item['filename']}\n"
            f"群組：{item['group_name']}\n"
            f"內容：\n{item['chunk_text']}"
        )

    context_text = "\n\n---\n\n".join(context_parts)

    prompt = f"""
你是一個文件問答助理。
你只能根據提供的文件內容回答問題，不可使用文件外知識補充。

請遵守以下原則：
1. 直接回答問題，不要重述使用者問題。
2. 不要輸出固定標籤，例如「重點答案：」、「依據：」、「補充說明：」。
3. 請根據問題類型，自行判斷最自然、最有幫助的回答方式。
4. 如果問題是在問概念、定義、語法或規則，而文件內容足以支持整理，你可以將文件中的資訊整理成較通用、較好理解的說法。
5. 如果文件內容只提供局部範例，不足以推出完整規則，就只回答文件中能確定的內容，不要自行延伸。
6. 若文件內容不足以回答，請只回答：根據目前提供的文件內容，無法確定答案。
7. 一律使用繁體中文，回答自然、簡潔、清楚。

【文件內容】
{context_text}

【使用者問題】
{question}

請直接輸出最終答案，不要加前言、標題或格式標記。
""".strip()

    try:
        response = requests.post(
            "http://localhost:11434/api/generate",
            json={
                "model": model_name,
                "prompt": prompt,
                "stream": False
            },
            timeout=120
        )
        response.raise_for_status()
        data = response.json()
        return data.get("response", "模型沒有回傳內容。").strip()
    except Exception as e:
        return f"Ollama 生成失敗：{str(e)}"