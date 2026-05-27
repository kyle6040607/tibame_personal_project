from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse

from core.template import templates
from services.auth_service import authenticate

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def home(request: Request):
    if request.session.get("username"):
        role = request.session.get("role")
        if role == "admin":
            return RedirectResponse(url="/admin/dashboard", status_code=303)
        return RedirectResponse(url="/user/dashboard", status_code=303)

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"message": "請登入 Local LLM Notebook"}
    )


@router.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    user = authenticate(username, password)

    if user:
        request.session["username"] = user.username
        request.session["role"] = user.role
        request.session["user_id"] = user.id
        if user.role == "admin":
            return RedirectResponse(url="/admin/dashboard", status_code=303)
        return RedirectResponse(url="/user/dashboard", status_code=303)

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"message": "登入失敗，帳號或密碼錯誤"}
    )


@router.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/", status_code=303)
