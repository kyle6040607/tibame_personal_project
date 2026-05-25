import logging
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse

from core.template import templates
from repositories.group_repository import get_groups
from services.rag_service import (
    search_document_chunks,
    rewrite_query_with_ollama,
    merge_results,
    expand_with_adjacent_chunks,
    generate_answer_with_ollama,
    rerank_results_with_ollama,
    search_document_chunks_by_vector,
)

logger = logging.getLogger(__name__)
router = APIRouter()


def _require_login(request: Request):
    """Return username if logged in, else None."""
    return request.session.get("username")


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
def user_dashboard(request: Request):
    username = _require_login(request)
    if not username:
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse(
        request=request,
        name="user/user_dashboard.html",
        context=build_user_context(username=username, groups=get_groups())
    )


@router.post("/ask", response_class=HTMLResponse)
async def ask_question(request: Request, question: str = Form(...)):
    username = _require_login(request)
    if not username:
        return RedirectResponse(url="/", status_code=303)

    form = await request.form()
    selected_group_ids = [int(x) for x in form.getlist("group_ids") if str(x).strip()]

    logger.info("ask: user=%s groups=%s question=%r", username, selected_group_ids, question)

    rewritten_query = rewrite_query_with_ollama(question)

    results_original = search_document_chunks(question, selected_group_ids)
    results_rewritten = search_document_chunks(rewritten_query, selected_group_ids)

    vector_results = search_document_chunks_by_vector(question, selected_group_ids)
    vector_results_rewritten = search_document_chunks_by_vector(rewritten_query, selected_group_ids)

    merged_results = merge_results(
        results_original,
        results_rewritten,
        vector_results,
        vector_results_rewritten,
        limit=25
    )

    logger.info("ask: keyword_orig=%d keyword_rewrite=%d vector=%d vector_rewrite=%d merged=%d",
                len(results_original), len(results_rewritten),
                len(vector_results), len(vector_results_rewritten), len(merged_results))

    top_relevant = rerank_results_with_ollama(question, merged_results, limit=5)

    best_score = max((r.get("relevance_score", 0) for r in top_relevant), default=0)
    if top_relevant and best_score >= 2:
        top_candidates = top_relevant[:5]
    else:
        logger.info("ask: rerank best_score=%d < 2, falling back to merged_results", best_score)
        top_candidates = merged_results[:5]

    results = expand_with_adjacent_chunks(top_candidates)
    answer = generate_answer_with_ollama(question, results)

    logger.info("ask: final_chunks=%d answer_len=%d", len(results), len(answer))

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
