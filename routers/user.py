from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse

from core.template import templates
from repositories.group_repository import get_groups
from services.rag_service import (
    search_document_chunks,
    rewrite_query_with_ollama,
    merge_results,
    generate_answer_with_ollama,
)

router = APIRouter()


def build_user_context(
    username: str,
    groups=None,
    selected_group_id=None,
    question="",
    results=None,
    answer="請輸入問題後送出。",
    rewritten_query=""
):
    return {
        "username": username,
        "message": "User 提問頁",
        "groups": groups or [],
        "selected_group_id": selected_group_id,
        "question": question,
        "results": results or [],
        "answer": answer,
        "rewritten_query": rewritten_query
    }


@router.get("/user/dashboard", response_class=HTMLResponse)
def user_dashboard(request: Request, username: str):
    return templates.TemplateResponse(
        request=request,
        name="user/user_dashboard.html",
        context=build_user_context(
            username=username,
            groups=get_groups()
        )
    )


@router.post("/ask", response_class=HTMLResponse)
def ask_question(
    request: Request,
    username: str = Form(...),
    question: str = Form(...),
    group_id: str = Form("")
):
    selected_group_id = int(group_id) if group_id else None

    rewritten_query = rewrite_query_with_ollama(question)

    results_original = search_document_chunks(question, selected_group_id)
    results_rewritten = search_document_chunks(rewritten_query, selected_group_id)
    results = merge_results(results_original, results_rewritten)

    answer = generate_answer_with_ollama(question, results)

    return templates.TemplateResponse(
        request=request,
        name="user/user_dashboard.html",
        context=build_user_context(
            username=username,
            groups=get_groups(),
            selected_group_id=selected_group_id,
            question=question,
            results=results,
            answer=answer,
            rewritten_query=rewritten_query
        )
    )