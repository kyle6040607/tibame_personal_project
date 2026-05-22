from fastapi import APIRouter, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse

from core.template import templates
from repositories.group_repository import get_groups, insert_group, delete_group_if_empty
from repositories.document_repository import get_documents, insert_document, delete_document_and_chunks
from services.auth_service import is_admin
from services.file_service import extract_text_from_file
from services.document_service import insert_document_chunks

router = APIRouter()


@router.get("/admin/dashboard", response_class=HTMLResponse)
def admin_dashboard(request: Request, username: str):
    return templates.TemplateResponse(
        request=request,
        name="admin/admin_dashboard.html",
        context={"username": username, "message": "Admin 管理目錄"}
    )


@router.get("/admin/upload", response_class=HTMLResponse)
def admin_upload_page(request: Request, username: str):
    return templates.TemplateResponse(
        request=request,
        name="admin/admin_upload.html",
        context={
            "username": username,
            "groups": get_groups(),
            "documents": get_documents(),
            "message": "上傳文件"
        }
    )


@router.get("/admin/groups", response_class=HTMLResponse)
def admin_groups_page(request: Request, username: str):
    return templates.TemplateResponse(
        request=request,
        name="admin/admin_groups.html",
        context={
            "username": username,
            "groups": get_groups(),
            "message": "新建群組"
        }
    )


@router.post("/add-group", response_class=HTMLResponse)
def add_group(
    request: Request,
    username: str = Form(...),
    group_name: str = Form(...),
    group_description: str = Form(...)
):
    if not is_admin(username):
        return RedirectResponse(url="/", status_code=303)

    insert_group(group_name, group_description)

    return templates.TemplateResponse(
        request=request,
        name="admin/admin_groups.html",
        context={
            "message": f"群組新增成功：{group_name}",
            "username": username,
            "groups": get_groups()
        }
    )


@router.post("/upload-document", response_class=HTMLResponse)
async def upload_document(
    request: Request,
    username: str = Form(...),
    title: str = Form(...),
    group_id: int = Form(...),
    file: UploadFile = File(...)
):
    if not is_admin(username):
        return templates.TemplateResponse(
            request=request,
            name="admin/admin_upload.html",
            context={
                "message": "你沒有權限上傳文件",
                "username": username,
                "groups": get_groups(),
                "documents": get_documents()
            }
        )

    content_bytes = await file.read()
    content_text = extract_text_from_file(file.filename, content_bytes)

    if content_text is None:
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

    document_id = insert_document(title, file.filename, content_text, group_id)
    insert_document_chunks(document_id, content_text)

    return templates.TemplateResponse(
        request=request,
        name="admin/admin_upload.html",
        context={
            "message": f"文件上傳成功：{file.filename}",
            "username": username,
            "groups": get_groups(),
            "documents": get_documents()
        }
    )


@router.get("/admin/delete", response_class=HTMLResponse)
def admin_delete_page(request: Request, username: str, group_id: int = None):
    documents = get_documents(group_id) if group_id else []

    return templates.TemplateResponse(
        request=request,
        name="admin/admin_delete.html",
        context={
            "username": username,
            "groups": get_groups(),
            "documents": documents,
            "selected_group_id": group_id,
            "message": "刪除文件"
        }
    )


@router.post("/delete-document")
def delete_document(
    username: str = Form(...),
    document_id: int = Form(...),
    group_id: int = Form(...)
):
    delete_document_and_chunks(document_id)
    return RedirectResponse(
        url=f"/admin/delete?username={username}&group_id={group_id}",
        status_code=303
    )


@router.post("/delete-group", response_class=HTMLResponse)
def delete_group(
    request: Request,
    username: str = Form(...),
    group_id: int = Form(...)
):
    if not is_admin(username):
        return templates.TemplateResponse(
            request=request,
            name="admin/admin_groups.html",
            context={
                "message": "你沒有權限刪除群組",
                "username": username,
                "groups": get_groups()
            }
        )

    success = delete_group_if_empty(group_id)
    message = (
        f"群組刪除成功，ID = {group_id}"
        if success else "此群組底下仍有文件，請先刪除文件後再刪除群組"
    )

    return templates.TemplateResponse(
        request=request,
        name="admin/admin_groups.html",
        context={
            "message": message,
            "username": username,
            "groups": get_groups()
        }
    )