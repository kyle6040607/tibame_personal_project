from pathlib import Path
import pyodbc
from fastapi import FastAPI, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from io import BytesIO
from pypdf import PdfReader
import requests

app = FastAPI()

BASE_DIR = Path(__file__).resolve().parent

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


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

@app.post("/delete-document", response_class=HTMLResponse)
def delete_document(
    request: Request,
    username: str = Form(...),
    document_id: int = Form(...),
    group_id: int = Form(None)
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
            name="admin/admin_delete.html",
            context={
                "message": "你沒有權限刪除文件",
                "username": username,
                "groups": get_groups(),
                "documents": get_documents(group_id),
                "selected_group_id": group_id
            }
        )

    cursor.execute("DELETE FROM documents WHERE id = ?", document_id)
    conn.commit()

    cursor.close()
    conn.close()

    return templates.TemplateResponse(
        request=request,
        name="admin/admin_delete.html",
        context={
            "message": f"文件刪除成功，ID = {document_id}",
            "username": username,
            "groups": get_groups(),
            "documents": get_documents(group_id),
            "selected_group_id": group_id
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
    results = search_document_chunks(question)

    if results:
        top = results[0]
        answer = f"根據目前最相關的文件片段，答案可能與《{top['title']}》有關，請先參考下方內容。"
    else:
        answer = "目前找不到相關 chunk 內容。"

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


def search_document_chunks(question: str):
    conn = get_connection()
    cursor = conn.cursor()

    keyword = f"%{question}%"
    cursor.execute(
        """
        SELECT TOP 5 c.id, c.chunk_index, c.chunk_text, d.title, d.filename, g.name AS group_name
        FROM document_chunks c
        INNER JOIN documents d ON c.document_id = d.id
        INNER JOIN document_groups g ON d.group_id = g.id
        WHERE c.chunk_text LIKE ? OR d.title LIKE ?
        ORDER BY d.id DESC, c.chunk_index ASC
        """,
        keyword,
        keyword,
    )
    rows = cursor.fetchall()

    results = []
    for row in rows:
        snippet = row.chunk_text[:300] if row.chunk_text else ""
        results.append({
            "chunk_id": row.id,
            "chunk_index": row.chunk_index,
            "title": row.title,
            "filename": row.filename,
            "group_name": row.group_name,
            "snippet": snippet
        })

    cursor.close()
    conn.close()
    return results

def generate_answer_with_ollama(question: str, results: list, model_name: str = "llama3:latest"):
    if not results:
        return "目前找不到相關文件內容，無法生成回答。"

    context_parts = []
    for item in results[:3]:
        context_parts.append(
            f"文件標題：{item['title']}\n"
            f"群組：{item['group_name']}\n"
            f"Chunk 編號：{item['chunk_index']}\n"
            f"內容：{item['snippet']}"
        )

    context_text = "\n\n---\n\n".join(context_parts)

    prompt = f"""
你是一個地端 LLM Notebook 助理。
請只能根據以下提供的文件內容回答問題，不要自行補充不存在的資訊。
如果文件內容不足以回答，請明確說「根據目前提供的文件內容，無法確定答案」。

【使用者問題】
{question}

【文件內容】
{context_text}

【回答要求】
1. 用繁體中文回答。
2. 先直接回答重點。
3. 若適合，可用條列整理。
4. 不要捏造文件中沒有的內容。
"""

    try:
        response = requests.post(
            "http://localhost:11434/api/generate",
            json={
                "model": "llama3:latest",
                "prompt": prompt,
                "stream": False
            },
            timeout=120
        )
        response.raise_for_status()
        data = response.json()
        return data.get("response", "模型沒有回傳內容。")
    except Exception as e:
        return f"Ollama 生成失敗：{str(e)}"