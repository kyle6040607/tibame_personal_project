import json
import logging
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse

from core.template import templates
from repositories.group_repository import get_groups
from repositories.user_group_repository import get_user_group_ids
from repositories.chat_history_repository import insert_chat_history, get_user_chat_history, update_chat_feedback
from services.rag_service import (
    search_document_chunks,
    rewrite_query_with_ollama,
    merge_results,
    expand_with_adjacent_chunks,
    generate_answer_with_ollama,
    generate_answer_streaming,
    rerank_results_with_ollama,
    search_document_chunks_by_vector,
)

logger = logging.getLogger(__name__)
router = APIRouter()


def _require_login(request: Request):
    return request.session.get("username")


def _get_permitted_groups(request: Request) -> list[dict]:
    """
    回傳該使用者有權限的群組清單。
    若未設定任何權限（user_group_permissions 為空），則回傳全部群組。
    Admin 永遠看到全部群組。
    """
    all_groups = get_groups()
    role = request.session.get("role")
    if role == "admin":
        return all_groups

    user_id = request.session.get("user_id")
    if not user_id:
        return all_groups

    permitted_ids = set(get_user_group_ids(user_id))
    if not permitted_ids:
        return all_groups

    return [g for g in all_groups if g["id"] in permitted_ids]


def build_user_context(
    username: str,
    groups=None,
    selected_group_ids=None,
    question="",
    results=None,
    answer="請輸入問題後送出。",
    rewritten_query="",
    history=None
):
    return {
        "username": username,
        "message": "User 提問頁",
        "groups": groups or [],
        "selected_group_ids": selected_group_ids or [],
        "question": question,
        "results": results or [],
        "answer": answer,
        "rewritten_query": rewritten_query,
        "history": history or [],
    }


def _do_rag(question: str, selected_group_ids: list[int]):
    """Run full RAG pipeline and return (rewritten_query, results)."""
    rewritten_query = rewrite_query_with_ollama(question)

    results_original = search_document_chunks(question, selected_group_ids)
    results_rewritten = search_document_chunks(rewritten_query, selected_group_ids)
    vector_results = search_document_chunks_by_vector(question, selected_group_ids)
    vector_results_rewritten = search_document_chunks_by_vector(rewritten_query, selected_group_ids)

    merged = merge_results(
        results_original, results_rewritten,
        vector_results, vector_results_rewritten,
        limit=25
    )

    logger.info("rag: keyword_orig=%d keyword_rewrite=%d vector=%d vector_rewrite=%d merged=%d",
                len(results_original), len(results_rewritten),
                len(vector_results), len(vector_results_rewritten), len(merged))

    top_relevant = rerank_results_with_ollama(question, merged, limit=5)
    best_score = max((r.get("relevance_score", 0) for r in top_relevant), default=0)
    top_candidates = top_relevant if (top_relevant and best_score >= 2) else merged[:5]

    results = expand_with_adjacent_chunks(top_candidates)
    return rewritten_query, results


def _serialize_result(r: dict) -> dict:
    return {
        "title": r.get("title", ""),
        "filename": r.get("filename", ""),
        "group_name": r.get("group_name", ""),
        "document_id": r.get("document_id"),
        "chunk_index": r.get("chunk_index"),
        "score": r.get("score", 0),
        "rrf_score": r.get("rrf_score", 0),
        "matched_tokens": r.get("matched_tokens", []),
        "snippet": r.get("snippet", "")[:300],
    }


@router.get("/user/dashboard", response_class=HTMLResponse)
def user_dashboard(request: Request):
    username = _require_login(request)
    if not username:
        return RedirectResponse(url="/", status_code=303)

    history = list(request.session.get("chat_history", []))
    permitted_groups = _get_permitted_groups(request)

    return templates.TemplateResponse(
        request=request,
        name="user/user_dashboard.html",
        context=build_user_context(username=username, groups=permitted_groups, history=history)
    )


@router.post("/ask", response_class=HTMLResponse)
async def ask_question(request: Request, question: str = Form(...)):
    username = _require_login(request)
    if not username:
        return RedirectResponse(url="/", status_code=303)

    form = await request.form()
    selected_group_ids = [int(x) for x in form.getlist("group_ids") if str(x).strip()]
    history = list(request.session.get("chat_history", []))
    permitted_groups = _get_permitted_groups(request)

    logger.info("ask: user=%s groups=%s question=%r", username, selected_group_ids, question)

    rewritten_query, results = _do_rag(question, selected_group_ids)
    answer = generate_answer_with_ollama(question, results, history=history)

    history.append({"question": question, "answer": answer})
    if len(history) > 10:
        history = history[-10:]
    request.session["chat_history"] = history

    user_id = request.session.get("user_id")
    if user_id:
        try:
            insert_chat_history(user_id, username, question, answer, selected_group_ids)
        except Exception as e:
            logger.warning("insert_chat_history failed: %s", e)

    logger.info("ask: final_chunks=%d answer_len=%d", len(results), len(answer))


    return templates.TemplateResponse(
        request=request,
        name="user/user_dashboard.html",
        context=build_user_context(
            username=username,
            groups=permitted_groups,
            selected_group_ids=selected_group_ids,
            question=question,
            results=results,
            answer=answer,
            rewritten_query=rewritten_query,
            history=history,
        )
    )


@router.post("/ask/stream")
def ask_question_stream(
    request: Request,
    question: str = Form(...),
    group_ids: list[int] = Form(default=[]),
):
    username = _require_login(request)
    if not username:
        def _unauth():
            yield f'data: {json.dumps({"type": "error", "message": "未登入，請重新整理頁面。"})}\n\n'
        return StreamingResponse(_unauth(), media_type="text/event-stream")

    history = list(request.session.get("chat_history", []))
    logger.info("ask_stream: user=%s groups=%s question=%r", username, group_ids, question)

    rewritten_query, results = _do_rag(question, group_ids)
    chunks_data = [_serialize_result(r) for r in results]

    def event_stream():
        yield f'data: {json.dumps({"type": "meta", "rewritten_query": rewritten_query, "chunks": chunks_data})}\n\n'

        full_answer = ""
        for token in generate_answer_streaming(question, results, history=history):
            full_answer += token
            yield f'data: {json.dumps({"type": "token", "text": token})}\n\n'

        logger.info("ask_stream: answer_len=%d", len(full_answer))
        yield f'data: {json.dumps({"type": "done", "answer": full_answer})}\n\n'

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/save-history")
def save_history(
    request: Request,
    question: str = Form(...),
    answer: str = Form(...),
    group_ids: list[int] = Form(default=[]),
):
    username = _require_login(request)
    if not username:
        return {"ok": False}

    history = list(request.session.get("chat_history", []))
    history.append({"question": question, "answer": answer})
    if len(history) > 10:
        history = history[-10:]
    request.session["chat_history"] = history

    chat_id = 0
    user_id = request.session.get("user_id")
    if user_id:
        try:
            chat_id = insert_chat_history(user_id, username, question, answer, group_ids)
        except Exception as e:
            logger.warning("insert_chat_history failed: %s", e)

    return {"ok": True, "chat_id": chat_id}


@router.post("/clear-history")
def clear_history(request: Request):
    if not _require_login(request):
        return RedirectResponse(url="/", status_code=303)
    request.session["chat_history"] = []
    return RedirectResponse(url="/user/dashboard", status_code=303)


@router.post("/feedback")
def save_feedback(
    request: Request,
    chat_id: int = Form(...),
    feedback: int = Form(...),
):
    username = _require_login(request)
    if not username:
        return {"ok": False, "error": "未登入"}
    if feedback not in (1, -1):
        return {"ok": False, "error": "無效的回饋值"}
    user_id = request.session.get("user_id")
    if not user_id:
        return {"ok": False, "error": "session 遺失"}
    try:
        update_chat_feedback(chat_id, user_id, feedback)
    except Exception as e:
        logger.warning("update_chat_feedback failed: %s", e)
        return {"ok": False, "error": str(e)}
    return {"ok": True}


@router.get("/user/history", response_class=HTMLResponse)
def user_history(request: Request):
    username = _require_login(request)
    if not username:
        return RedirectResponse(url="/", status_code=303)

    user_id = request.session.get("user_id")
    db_history = []
    if user_id:
        try:
            rows = get_user_chat_history(user_id, limit=50)
            db_history = [
                {
                    "question": r.question,
                    "answer": r.answer,
                    "created_at": str(r.created_at)[:16],
                }
                for r in rows
            ]
        except Exception as e:
            logger.warning("get_user_chat_history failed: %s", e)

    return templates.TemplateResponse(
        request=request,
        name="user/user_history.html",
        context={"username": username, "message": "我的對話記錄", "history": db_history}
    )
