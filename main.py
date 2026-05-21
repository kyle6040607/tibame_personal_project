from pathlib import Path
import pyodbc
from fastapi import FastAPI, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from io import BytesIO
from pypdf import PdfReader

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
    results = search_documents(question)

    if results:
        answer = "以下是根據文件找到的相關內容："
    else:
        answer = "目前找不到相關文件內容。"

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

    cursor.close()
    conn.close()

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