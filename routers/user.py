from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse

from core.template import templates
from repositories.group_repository import get_groups
from services.rag_service import (
    search_document_chunks,
    rewrite_query_with_ollama,
    merge_results,
    expand_with_adjacent_chunks,
    generate_answer_with_ollama,
    rerank_results_with_ollama,
)

router = APIRouter()


def build_user_context(
    username: str,
    groups=None,
    selected_group_ids=None,
    question="",
    results=None,
    answer="請輸入問題後送出。",
    rewritten_query=""
):
    return {
        "username": username,
        "message": "User 提問頁",
        "groups": groups or [],
        "selected_group_ids": selected_group_ids or [],
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
            groups=get_groups(),
            selected_group_ids=[]
        )
    )


@router.post("/ask", response_class=HTMLResponse)
async def ask_question(
    request: Request,
    username: str = Form(...),
    question: str = Form(...)
):
    form = await request.form()
    selected_group_ids = [int(x) for x in form.getlist("group_ids") if str(x).strip()]

    rewritten_query = rewrite_query_with_ollama(question)

    results_original = []
    results_rewritten = []

    for gid in selected_group_ids:
        results_original.extend(search_document_chunks(question, gid))
        results_rewritten.extend(search_document_chunks(rewritten_query, gid))

    merged_results = merge_results(results_original, results_rewritten)

    # ollama判斷這是不是廢話
    top_relevant = rerank_results_with_ollama(question, merged_results, limit=5)

    #  chunk 做相鄰擴展
    results = expand_with_adjacent_chunks(top_relevant)

    answer = generate_answer_with_ollama(question, results)

    return templates.TemplateResponse(
        request=request,
        name="user/user_dashboard.html",
        context=build_user_context(
            username=username,
            groups=get_groups(),
            selected_group_ids=selected_group_ids,
            question=question,
            results=results,
            answer=answer,
            rewritten_query=rewritten_query
        )
    )