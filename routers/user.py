from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse

from core.template import templates
from services.rag_service import (
    search_document_chunks,
    rewrite_query_with_ollama,
    merge_results,
    generate_answer_with_ollama,
)

router = APIRouter()


def build_user_context(username: str, question="", results=None, answer="請輸入問題後送出。", rewritten_query=""):
    return {
        "username": username,
        "message": "User 提問頁",
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
        context=build_user_context(username=username)
    )


@router.post("/ask", response_class=HTMLResponse)
def ask_question(
    request: Request,
    username: str = Form(...),
    question: str = Form(...)
):
    rewritten_query = rewrite_query_with_ollama(question)

    results_original = search_document_chunks(question)
    results_rewritten = search_document_chunks(rewritten_query)
    results = merge_results(results_original, results_rewritten)

    answer = generate_answer_with_ollama(question, results)

    return templates.TemplateResponse(
        request=request,
        name="user/user_dashboard.html",
        context=build_user_context(
            username=username,
            question=question,
            results=results,
            answer=answer,
            rewritten_query=rewritten_query
        )
    )