import re
import requests
from repositories.chunk_repository import search_chunk_candidates, get_adjacent_chunks


def tokenize_query(query: str):
    query = (query or "").strip()
    if not query:
        return []

    tokens = re.split(r"[\s,，。！？；：/\\|]+", query)
    tokens = [t.strip() for t in tokens if t.strip()]
    return tokens[:8]


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
    return results[:20]


def rewrite_query_with_ollama(question: str, model_name: str = "llama3:latest"):
    prompt = f"""
你是一個文件檢索查詢重寫器。
請把使用者問題改寫成適合搜尋教材、講義、技術文件的小搜尋詞。

規則：
1. 保留原意。
2. 保留技術名詞，例如 dict、list、tuple、set、DataFrame、merge、groupby。
3. 如果是「怎麼用」、「如何使用」這類問句，改寫成「主題 + 用法」。
4. 如果有可能的中英文同義詞，可補上最常見寫法，但不要太長。
5. 補充盡量完整。

範例：
- dict要怎麼用呢 -> Python dict 用法 dictionary
- dataframe怎麼篩選 -> pandas DataFrame 篩選 filter loc iloc
- groupby是什麼 -> pandas groupby 用法 分組聚合

使用者問題：
{question}
""".strip()

    try:
        response = requests.post(
            "http://localhost:11434/api/generate",
            json={"model": model_name, "prompt": prompt, "stream": False},
            timeout=60
        )
        response.raise_for_status()
        data = response.json()
        rewritten = data.get("response", "").strip()
        return rewritten if rewritten else question
    except Exception:
        return question


def merge_results(*result_lists, k: int = 60, limit: int = 8):
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


def generate_answer_with_ollama(question: str, results: list, model_name: str = "llama3:latest"):
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

    try:
        response = requests.post(
            "http://localhost:11434/api/generate",
            json={"model": model_name, "prompt": prompt, "stream": False},
            timeout=120
        )
        response.raise_for_status()
        data = response.json()
        return data.get("response", "模型沒有回傳內容。").strip()
    except Exception as e:
        return f"Ollama 生成失敗：{str(e)}"