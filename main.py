from pathlib import Path
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import pyodbc

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

@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"message": "請登入 Local LLM Notebook"}
    )

@app.post("/login", response_class=HTMLResponse)
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT username, role FROM users WHERE username = ? AND password = ?",
        username,
        password
    )
    user = cursor.fetchone()

    groups = []

    if user and user.role == "admin":
        cursor.execute("SELECT id, name, description FROM document_groups")
        rows = cursor.fetchall()

        for row in rows:
            groups.append({
                "id": row.id,
                "name": row.name,
                "description": row.description
            })

    cursor.close()
    conn.close()

    if user:
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "message": f"登入成功，歡迎 {user.username}",
                "role": user.role,
                "username": user.username,
                "groups": groups
            }
        )
    else:
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "message": "登入失敗，帳號或密碼錯誤",
                "role": None,
                "groups": []
            }
        )