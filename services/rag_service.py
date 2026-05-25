import re
import logging
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

from repositories.chunk_repository import search_chunk_candidates, get_adjacent_chunks
from repositories.vector_repository import query_chunk_embeddings
from services.embedding_service import get_embedding
from core.config import OLLAMA_URL, LLM_MODEL

logger = logging.getLogger(__name__)

_CJK_CHAR = re.compile(r'[一-鿿㐀-䶿]')
_CJK_ASCII_BOUNDARY = re.compile(
    r'(?<=[a-zA-Z0-9])(?=[一-鿿㐀-䶿])'
    r'|'
    r'(?<=[一-鿿㐀-䶿])(?=[a-zA-Z0-9])'
)


def tokenize_query(query: str):
    query = (query or "").strip()
    if not query:
        return []

    raw = re.split(r"[\s,，。！？；：/\\|]+", query)
    raw = [t.strip() for t in raw if t.strip()]

    tokens = []
    for t in raw:
        # Split at CJK<->ASCII boundaries: "dict怎麼" -> ["dict", "怎麼"]
        parts = _CJK_ASCII_BOUNDARY.split(t)
        parts = [p for p in parts if p]

        for part in parts:
            tokens.append(part)
            # For long pure-CJK segments, add 2-char bigrams for sub-phrase matching
            if len(part) >= 4 and _CJK_CHAR.search(part):
                bigrams = [part[i:i+2] for i in range(len(part) - 1)
                           if _CJK_CHAR.search(part[i:i+2])]
                tokens.extend(bigrams)

    # Deduplicate while preserving order, cap at 16
    seen = set()
    result = []
    for t in tokens:
        if t not in seen:
            seen.add(t)
            result.append(t)
    result = result[:16]
    logger.debug("tokenize_query: %s -> %s", query, result)
    return result


def search_document_chunks(query: str, group_id: int | None = None):
    tokens = tokenize_query(query)
    if not tokens:
        return []

    rows = search_chunk_candidates(tokens, group_id)

    results = []
    seen_chunk_ids = set()

    for row in rows:
        if row.id in seen_chunk_ids:
            continue
        seen_chunk_ids.add(row.id)

        full_text = row.chunk_text or ""
        text_lower = full_text.lower()
        title_lower = (row.title or "").lower()
        filename_lower = (row.filename or "").lower()

        score = 0
        matched_tokens = []

        for token in tokens:
            token_lower = token.lower()
            if token_lower in title_lower:
                score += 4
                matched_tokens.append(token)
            elif token_lower in filename_lower:
                score += 3
                matched_tokens.append(token)
            elif token_lower in text_lower:
                score += 1
                matched_tokens.append(token)

        results.append({
            "chunk_id": row.id,
            "document_id": row.document_id,
            "chunk_index": row.chunk_index,
            "title": row.title,
            "filename": row.filename,
            "group_name": row.group_name,
            "chunk_text": full_text,
            "snippet": full_text[:300],
            "score": score,
            "matched_tokens": matched_tokens
        })

    results.sort(key=lambda x: (x["score"], len(x["matched_tokens"])), reverse=True)
    nonzero = [r for r in results if r["score"] > 0]
    final = (nonzero if nonzero else results)[:50]
    logger.info("keyword search group=%s query=%r -> %d results (%d nonzero)",
                group_id, query, len(final), len(nonzero))
    return final


def rewrite_query_with_ollama(question: str, model_name: str = LLM_MODEL):
    prompt = f"""
你是一個文件檢索查詢重寫器。
請把使用者問題改寫成適合搜尋教材、講義、技術文件的小搜尋詞。

規則：
1. 保留原意。
2. 保留技術名詞，例如 dict、list、tuple、set、DataFrame、merge、groupby。
3. 如果是「怎麼用」、「如何使用」這類問句，改寫成「主題 + 用法」。
4. 如果有可能的中英文同義詞，可補上最常見寫法，但不要太長。
5. 輸出 1 行即可，不要解釋。

範例：
- dict要怎麼用呢 -> Python dict 用法 dictionary
- dataframe怎麼篩選 -> pandas DataFrame 篩選 filter loc iloc
- groupby是什麼 -> pandas groupby 用法 分組聚合

使用者問題：
{question}
""".strip()

    try:
        response = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={"model": model_name, "prompt": prompt, "stream": False},
            timeout=60
        )
        response.raise_for_status()
        data = response.json()
        rewritten = data.get("response", "").strip()
        result = rewritten if rewritten else question
        logger.info("rewrite_query: %r -> %r", question, result)
        return result
    except Exception as e:
        logger.warning("rewrite_query failed: %s", e)
        return question


def merge_results(*result_lists, k: int = 60, limit: int = 20):
    fused = {}

    for result_list in result_lists:
        for rank, item in enumerate(result_list, start=1):
            chunk_id = item["chunk_id"]
            rrf_score = 1 / (k + rank)

            if chunk_id not in fused:
                fused[chunk_id] = dict(item)
                fused[chunk_id]["rrf_score"] = 0.0
                fused[chunk_id]["hit_count"] = 0

            fused[chunk_id]["rrf_score"] += rrf_score
            fused[chunk_id]["hit_count"] += 1

            existing_tokens = set(fused[chunk_id].get("matched_tokens", []))
            new_tokens = set(item.get("matched_tokens", []))
            fused[chunk_id]["matched_tokens"] = list(existing_tokens | new_tokens)

            fused[chunk_id]["score"] = max(
                fused[chunk_id].get("score", 0),
                item.get("score", 0)
            )

    merged = list(fused.values())
    merged.sort(
        key=lambda x: (x["rrf_score"], x["hit_count"], x["score"], len(x["matched_tokens"])),
        reverse=True
    )
    return merged[:limit]


def expand_with_adjacent_chunks(results: list):
    expanded = []
    seen = set()

    for item in results[:5]:
        key = (item["document_id"], item["chunk_index"])
        if key not in seen:
            expanded.append(item)
            seen.add(key)

        adjacent_rows = get_adjacent_chunks(item["document_id"], item["chunk_index"])
        for row in adjacent_rows:
            adj_key = (row.document_id, row.chunk_index)
            if adj_key in seen:
                continue

            expanded.append({
                "chunk_id": row.id,
                "document_id": row.document_id,
                "chunk_index": row.chunk_index,
                "title": item["title"],
                "filename": item["filename"],
                "group_name": item["group_name"],
                "chunk_text": row.chunk_text or "",
                "snippet": (row.chunk_text or "")[:300],
                "score": item.get("score", 0) - 0.2,
                "matched_tokens": item.get("matched_tokens", []),
            })
            seen.add(adj_key)

    expanded.sort(key=lambda x: (x["document_id"], x["chunk_index"]))
    return expanded


def generate_answer_with_ollama(question: str, results: list, model_name: str = LLM_MODEL):
    if not results:
        return "根據目前提供的文件內容，無法確定答案。"

    context_parts = []
    for item in results[:6]:
        context_parts.append(
            f"文件標題：{item['title']}\n"
            f"檔名：{item['filename']}\n"
            f"群組：{item['group_name']}\n"
            f"段落編號：{item['chunk_index']}\n"
            f"內容：\n{item['chunk_text']}"
        )

    context_text = "\n\n---\n\n".join(context_parts)

    prompt = f"""
你是一個文件問答助理。
你的任務是根據提供的文件片段回答問題。

請遵守以下原則：
1. 只能根據文件內容回答。
2. 若文件內容不足以支持答案，請回答：根據目前提供的文件內容，無法確定答案。
3. 不可使用文件外知識補充。
4. 如果多份文件內容有差異，請明確指出差異，不要自行統一。
5. 一律使用繁體中文，回答自然、簡潔、清楚。
6. 回答完後，另起一行輸出來源，格式為：來源：文件標題（段落編號）, 文件標題（段落編號）

【文件內容】
{context_text}

【使用者問題】
{question}

請直接輸出最終答案。
""".strip()

    logger.info("generate_answer: question=%r, context_chunks=%d", question, len(results))
    try:
        response = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={"model": model_name, "prompt": prompt, "stream": False},
            timeout=120
        )
        response.raise_for_status()
        data = response.json()
        answer = data.get("response", "模型沒有回傳內容。").strip()
        logger.info("generate_answer: done, answer_len=%d", len(answer))
        return answer
    except Exception as e:
        logger.error("generate_answer failed: %s", e)
        return f"Ollama 生成失敗：{str(e)}"


def score_chunk_relevance_with_ollama(question: str, chunk_text: str, model_name: str = LLM_MODEL) -> int:
    prompt = f"""
你是一個文件檢索評分器。
請判斷下面的文件片段，是否真的有助於回答使用者問題。

評分規則：
- 0 分：完全無關
- 1 分：只提到關鍵字，但幾乎不能回答
- 2 分：部分相關，但資訊不足
- 3 分：相關，能回答一部分
- 4 分：高度相關，能回答大部分
- 5 分：直接回答問題

只輸出一個整數（0 到 5），不要解釋。

【使用者問題】
{question}

【文件片段】
{chunk_text}
""".strip()

    try:
        response = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={"model": model_name, "prompt": prompt, "stream": False},
            timeout=60
        )
        response.raise_for_status()
        data = response.json()
        text = data.get("response", "").strip()
        score = int(text) if text.isdigit() else 0
        return max(0, min(score, 5))
    except Exception as e:
        logger.warning("score_chunk_relevance failed: %s", e)
        return 0


def rerank_results_with_ollama(question: str, results: list, limit: int = 5) -> list:
    if not results:
        return []

    candidates = results[:3]

    # Score all 3 candidates in parallel to reduce latency
    with ThreadPoolExecutor(max_workers=3) as executor:
        future_to_item = {
            executor.submit(score_chunk_relevance_with_ollama, question, item["chunk_text"]): item
            for item in candidates
        }
        reranked = []
        for future in as_completed(future_to_item):
            item = future_to_item[future]
            enriched = dict(item)
            enriched["relevance_score"] = future.result()
            reranked.append(enriched)

    reranked.sort(
        key=lambda x: (
            x.get("relevance_score", 0),
            x.get("rrf_score", 0),
            x.get("score", 0),
            len(x.get("matched_tokens", [])),
        ),
        reverse=True,
    )
    return reranked[:limit]


def search_document_chunks_by_vector(query: str, group_ids: list[int] | None = None):
    query = (query or "").strip()
    if not query:
        return []

    query_embedding = get_embedding(query)
    if not query_embedding:
        logger.warning("vector search: empty embedding for query=%r", query)
        return []

    result = query_chunk_embeddings(
        query_embedding=query_embedding,
        group_ids=group_ids,
        n_results=25
    )

    ids = result.get("ids", [[]])[0]
    docs = result.get("documents", [[]])[0]
    metas = result.get("metadatas", [[]])[0]

    logger.info("vector search: query=%r groups=%s -> %d results", query, group_ids, len(ids))
    output = []
    seen_chunk_ids = set()

    for chunk_id, chunk_text, meta in zip(ids, docs, metas):
        cid = int(chunk_id)
        if cid in seen_chunk_ids:
            continue
        seen_chunk_ids.add(cid)

        output.append({
            "chunk_id": cid,
            "document_id": meta["document_id"],
            "chunk_index": meta["chunk_index"],
            "title": meta["title"],
            "filename": meta["filename"],
            "group_name": meta["group_name"],
            "chunk_text": chunk_text,
            "snippet": chunk_text[:300],
            "score": 0,
            "matched_tokens": [],
        })

    return output
