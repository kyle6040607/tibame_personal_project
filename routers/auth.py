from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse

from core.template import templates
from repositories.user_repository import get_user_by_username_and_password

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def home(request: Request, error: str = None):
    message = "請登入 Local LLM Notebook"
    if error:
        message = "登入失敗，帳號或密碼錯誤"

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"message": message}
    )


@router.post("/login")
def login(username: str = Form(...), password: str = Form(...)):
    user = get_user_by_username_and_password(username, password)

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