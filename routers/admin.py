import hashlib
import logging

from fastapi import APIRouter, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse

from core.template import templates
from core.config import MAX_UPLOAD_MB
from services.document_service import insert_document_chunks
from services.embedding_service import index_document_chunks
from services.auth_service import is_admin
from services.file_service import extract_text_from_file
from repositories.group_repository import get_groups, insert_group, delete_group_if_empty
from repositories.document_repository import get_documents, insert_document, delete_document_and_chunks, document_exists_by_hash
from repositories.vector_repository import delete_embeddings_by_document
from repositories.user_repository import get_all_users, create_user, delete_user, username_exists
from services.auth_service import hash_password

logger = logging.getLogger(__name__)
router = APIRouter()


def _require_admin(request: Request):
    """Return username if admin, else None."""
    username = request.session.get("username")
    role = request.session.get("role")
    if not username or role != "admin":
        return None
    return username


@router.get("/admin/dashboard", response_class=HTMLResponse)
def admin_dashboard(request: Request):
    username = _require_admin(request)
    if not username:
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse(
        request=request,
        name="admin/admin_dashboard.html",
        context={"username": username, "message": "Admin 管理目錄"}
    )


@router.get("/admin/upload", response_class=HTMLResponse)
def admin_upload_page(request: Request):
    username = _require_admin(request)
    if not username:
        return RedirectResponse(url="/", status_code=303)
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
def admin_groups_page(request: Request):
    username = _require_admin(request)
    if not username:
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse(
        request=request,
        name="admin/admin_groups.html",
        context={"username": username, "groups": get_groups(), "message": "新建群組"}
    )


@router.post("/add-group", response_class=HTMLResponse)
def add_group(
    request: Request,
    group_name: str = Form(...),
    group_description: str = Form(...)
):
    username = _require_admin(request)
    if not username:
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
    title: str = Form(...),
    group_id: int = Form(...),
    files: list[UploadFile] = File(...)
):
    username = _require_admin(request)
    if not username:
        return RedirectResponse(url="/", status_code=303)

    success_files = []
    failed_files = []

    for file in files:
        content_bytes = await file.read()

        if len(content_bytes) > MAX_UPLOAD_MB * 1024 * 1024:
            logger.warning("upload reject: file=%s size=%dMB exceeds limit %dMB",
                           file.filename, len(content_bytes) // (1024 * 1024), MAX_UPLOAD_MB)
            failed_files.append(f"{file.filename}（檔案過大，上限 {MAX_UPLOAD_MB}MB）")
            continue

        file_hash = hashlib.sha256(content_bytes).hexdigest()

        if document_exists_by_hash(file_hash):
            logger.info("upload skip: file=%s already exists (hash match)", file.filename)
            failed_files.append(f"{file.filename}（已上傳過）")
            continue

        content_text = extract_text_from_file(file.filename, content_bytes)

        if content_text is None:
            failed_files.append(f"{file.filename}（不支援的格式）")
            continue

        if not content_text.strip():
            failed_files.append(f"{file.filename}（沒有擷取到文字）")
            continue

        final_title = title.strip() if len(files) == 1 and title.strip() else file.filename

        document_id = insert_document(
            final_title, file.filename, content_text, group_id, file_hash
        )
        insert_document_chunks(document_id, content_text)
        index_document_chunks(document_id)
        success_files.append(file.filename)
        logger.info("upload success: user=%s file=%s document_id=%d group_id=%d",
                    username, file.filename, document_id, group_id)

    if success_files and failed_files:
        message = f"成功 {len(success_files)} 個，失敗 {len(failed_files)} 個"
    elif success_files:
        message = f"成功上傳 {len(success_files)} 個檔案"
    else:
        message = "上傳失敗，可能有以下原因：\n" + "\n".join(failed_files)

    return templates.TemplateResponse(
        request=request,
        name="admin/admin_upload.html",
        context={
            "message": message,
            "username": username,
            "groups": get_groups(),
            "documents": get_documents()
        }
    )


@router.get("/admin/delete", response_class=HTMLResponse)
def admin_delete_page(request: Request, group_id: int = None):
    username = _require_admin(request)
    if not username:
        return RedirectResponse(url="/", status_code=303)

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
def delete_document(request: Request, document_id: int = Form(...), group_id: int = Form(...)):
    username = _require_admin(request)
    if not username:
        return RedirectResponse(url="/", status_code=303)

    delete_document_and_chunks(document_id)
    delete_embeddings_by_document(document_id)
    return RedirectResponse(url=f"/admin/delete?group_id={group_id}", status_code=303)


@router.get("/admin/users", response_class=HTMLResponse)
def admin_users_page(request: Request):
    username = _require_admin(request)
    if not username:
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse(
        request=request,
        name="admin/admin_users.html",
        context={
            "username": username,
            "users": get_all_users(),
            "message": "帳號管理",
            "error": None,
            "success": None,
        }
    )


@router.post("/admin/create-user", response_class=HTMLResponse)
def create_user_route(
    request: Request,
    new_username: str = Form(...),
    new_password: str = Form(...),
    role: str = Form(...)
):
    username = _require_admin(request)
    if not username:
        return RedirectResponse(url="/", status_code=303)

    error = None
    success = None

    if role not in ("admin", "user"):
        error = "角色必須是 admin 或 user。"
    elif not new_username.strip():
        error = "帳號名稱不能為空白。"
    elif not new_password:
        error = "密碼不能為空白。"
    elif username_exists(new_username.strip()):
        error = f"帳號「{new_username.strip()}」已存在。"
    else:
        create_user(new_username.strip(), hash_password(new_password), role)
        logger.info("admin=%s created user=%s role=%s", username, new_username.strip(), role)
        success = f"帳號「{new_username.strip()}」建立成功，角色：{role}。"

    return templates.TemplateResponse(
        request=request,
        name="admin/admin_users.html",
        context={
            "username": username,
            "users": get_all_users(),
            "message": "帳號管理",
            "error": error,
            "success": success,
        }
    )


@router.post("/admin/delete-user")
def delete_user_route(request: Request, user_id: int = Form(...)):
    username = _require_admin(request)
    if not username:
        return RedirectResponse(url="/", status_code=303)
    logger.info("admin=%s deleted user_id=%d", username, user_id)
    delete_user(user_id)
    return RedirectResponse(url="/admin/users", status_code=303)


@router.post("/delete-group", response_class=HTMLResponse)
def delete_group(request: Request, group_id: int = Form(...)):
    username = _require_admin(request)
    if not username:
        return RedirectResponse(url="/", status_code=303)

    success = delete_group_if_empty(group_id)
    message = (
        f"群組刪除成功，ID = {group_id}"
        if success else "此群組底下仍有文件，請先刪除文件後再刪除群組"
    )

    return templates.TemplateResponse(
        request=request,
        name="admin/admin_groups.html",
        context={"message": message, "username": username, "groups": get_groups()}
    )
