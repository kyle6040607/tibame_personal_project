import re
import json
import logging
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

from repositories.chunk_repository import search_chunk_candidates, get_adjacent_chunks
from repositories.vector_repository import query_chunk_embeddings
from services.embedding_service import get_embedding
from core.config import OLLAMA_URL, LLM_MODEL

logger = logging.getLogger(__name__)

# 向量距離上限（chroma collection 已改為 cosine，距離範圍 0~2，越小越相似）。
# 這只是雜訊過濾；最終排序仍交給 RRF + rerank。可視 embedding 模型微調。
_VECTOR_DISTANCE_MAX = 0.75
# LLM rerank 要評分的候選數量（原本只看前 5，導致融合後第 6~N 名永遠救不回來）。
_RERANK_POOL = 10

_CJK_CHAR = re.compile(r'[一-鿿㐀-䶿]')
_CJK_ASCII_BOUNDARY = re.compile(
    r'(?<=[a-zA-Z0-9])(?=[一-鿿㐀-䶿])'
    r'|'
    r'(?<=[一-鿿㐀-䶿])(?=[a-zA-Z0-9])'
)
_CJK_STOPWORDS = frozenset(
    "的了是在有不也和都就被把但而及或以與且對為如到從由上下來去用所又還更很太已再"
    "它他她我你您其各每些那這該此之乎者也哉矣焉"
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

    # Remove single-char CJK stop words (too broad for keyword matching)
    tokens = [t for t in tokens if not (len(t) == 1 and t in _CJK_STOPWORDS)]

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


def search_document_chunks(query: str, group_ids: list[int] | None = None):
    tokens = tokenize_query(query)
    if not tokens:
        return []

    rows = search_chunk_candidates(tokens, group_ids)

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
    logger.info("keyword search groups=%s query=%r -> %d results (%d nonzero)",
                group_ids, query, len(final), len(nonzero))
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
            json={"model": model_name, "prompt": prompt, "stream": False,
                  "options": {"temperature": 0.1}},
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
    # 依「相關度順序」逐一展開每個主段，把它的前後鄰段（依閱讀順序）緊接在後。
    # 不做全域位置排序：保留 rerank/RRF 排出的優先序，確保最相關的段落不會在
    # 後續 build_context_text 的 [:N] 截斷中被丟掉。
    expanded = []
    seen = set()

    for item in results[:5]:
        adjacent_rows = get_adjacent_chunks(item["document_id"], item["chunk_index"])

        # 把主段與鄰段彙整成 index -> dict，再依 chunk_index（閱讀順序）輸出
        by_index = {
            item["chunk_index"]: item
        }
        for row in adjacent_rows:
            if row.chunk_index in by_index:
                continue
            by_index[row.chunk_index] = {
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
            }

        for idx in sorted(by_index):
            key = (item["document_id"], idx)
            if key in seen:
                continue
            seen.add(key)
            expanded.append(by_index[idx])

    return expanded


def build_context_text(results: list, max_chars: int = 4000) -> str:
    parts = []
    total = 0
    for item in results[:6]:
        chunk = (
            f"文件標題：{item['title']}\n"
            f"檔名：{item['filename']}\n"
            f"群組：{item['group_name']}\n"
            f"段落編號：{item['chunk_index']}\n"
            f"內容：\n{item['chunk_text']}"
        )
        if total > 0 and total + len(chunk) > max_chars:
            logger.warning("context truncated: %d chars, %d/%d chunks included",
                           total, len(parts), len(results))
            break
        parts.append(chunk)
        total += len(chunk)
    return "\n\n---\n\n".join(parts)


def build_answer_prompt(question: str, context_text: str, history: list | None = None) -> str:
    history_section = ""
    if history:
        lines = []
        for entry in history[-3:]:
            lines.append(f"使用者：{entry['question']}")
            preview = entry["answer"][:300].replace("\n", " ")
            lines.append(f"助理：{preview}")
        history_section = "【對話歷史】\n" + "\n".join(lines) + "\n\n"

    return f"""你是一個文件問答助理。根據提供的文件片段回答問題。

規則：
1. 只能根據文件內容回答。
2. 若文件內容不足，回答：根據目前提供的文件內容，無法確定答案。
3. 不可使用文件外知識補充。
4. 若多份文件有差異，明確指出差異。
5. 一律使用繁體中文，自然、簡潔、清楚。
6. 輸出格式固定如下：

【回答】
（在此填寫回答內容）

【來源】
- 文件標題（第N段）

{history_section}【文件內容】
{context_text}

【使用者問題】
{question}

請直接輸出最終答案。""".strip()


def generate_answer_with_ollama(question: str, results: list, history: list | None = None, model_name: str = LLM_MODEL):
    if not results:
        return "根據目前提供的文件內容，無法確定答案。"

    context_text = build_context_text(results)
    prompt = build_answer_prompt(question, context_text, history)

    logger.info("generate_answer: question=%r, context_chunks=%d", question, len(results))
    try:
        response = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={"model": model_name, "prompt": prompt, "stream": False,
                  "options": {"temperature": 0.3}},
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


def generate_answer_streaming(question: str, results: list, history: list | None = None, model_name: str = LLM_MODEL):
    """Sync generator yielding answer tokens one by one via Ollama streaming API."""
    if not results:
        yield "根據目前提供的文件內容，無法確定答案。"
        return

    context_text = build_context_text(results)
    prompt = build_answer_prompt(question, context_text, history)

    logger.info("generate_answer_streaming: question=%r, context_chunks=%d", question, len(results))
    try:
        response = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={"model": model_name, "prompt": prompt, "stream": True,
                  "options": {"temperature": 0.3}},
            timeout=120,
            stream=True
        )
        response.raise_for_status()
        for line in response.iter_lines():
            if not line:
                continue
            data = json.loads(line)
            token = data.get("response", "")
            if token:
                yield token
            if data.get("done"):
                break
    except Exception as e:
        logger.error("generate_answer_streaming failed: %s", e)
        yield f"\n[生成失敗：{str(e)}]"


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
            json={"model": model_name, "prompt": prompt, "stream": False,
                  "options": {"temperature": 0.1}},
            timeout=60
        )
        response.raise_for_status()
        data = response.json()
        text = data.get("response", "").strip()
        # 本地模型常回 "4分"、"分數：3"、"4." 等，不能用 isdigit() 整段判斷，
        # 否則幾乎都解析成 0，等於 rerank 失效。改抓回覆中第一個整數。
        m = re.search(r"\d+", text)
        score = int(m.group()) if m else 0
        return max(0, min(score, 5))
    except Exception as e:
        logger.warning("score_chunk_relevance failed: %s", e)
        return 0


def rerank_results_with_ollama(question: str, results: list, limit: int = 5) -> list:
    if not results:
        return []

    candidates = results[:_RERANK_POOL]

    # Score candidates in parallel to reduce latency
    with ThreadPoolExecutor(max_workers=min(5, len(candidates))) as executor:
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
        n_results=50
    )

    ids = result.get("ids", [[]])[0]
    docs = result.get("documents", [[]])[0]
    metas = result.get("metadatas", [[]])[0]
    distances = result.get("distances", [[]])[0]

    logger.info("vector search: query=%r groups=%s -> %d results", query, group_ids, len(ids))
    output = []
    seen_chunk_ids = set()

    for chunk_id, chunk_text, meta, dist in zip(ids, docs, metas, distances):
        if dist > _VECTOR_DISTANCE_MAX:
            continue
        cid = int(chunk_id)
        if cid in seen_chunk_ids:
            continue
        seen_chunk_ids.add(cid)

        meta = meta or {}
        output.append({
            "chunk_id": cid,
            "document_id": meta.get("document_id"),
            "chunk_index": meta.get("chunk_index"),
            "title": meta.get("title", ""),
            "filename": meta.get("filename", ""),
            "group_name": meta.get("group_name", ""),
            "chunk_text": chunk_text,
            "snippet": chunk_text[:300],
            "score": 0,
            "matched_tokens": [],
        })

    return output
