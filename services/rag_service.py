import re
import requests
from repositories.chunk_repository import search_chunk_candidates


def tokenize_query(query: str):
    query = (query or "").strip()
    if not query:
        return []

    tokens = re.split(r"[\s,，。！？；：/\\|]+", query)
    tokens = [t.strip() for t in tokens if t.strip()]
    return tokens[:8]


def search_document_chunks(query: str):
    tokens = tokenize_query(query)
    if not tokens:
        return []

    rows = search_chunk_candidates(tokens)

    results = []
    seen_chunk_ids = set()

    for row in rows:
        if row.id in seen_chunk_ids:
            continue
        seen_chunk_ids.add(row.id)

        full_text = row.chunk_text or ""
        text_lower = full_text.lower()
        title_lower = (row.title or "").lower()

        score = 0
        matched_tokens = []

        for token in tokens:
            token_lower = token.lower()
            if token_lower in title_lower:
                score += 3
                matched_tokens.append(token)
            elif token_lower in text_lower:
                score += 1
                matched_tokens.append(token)

        results.append({
            "chunk_id": row.id,
            "chunk_index": row.chunk_index,
            "title": row.title,
            "filename": row.filename,
            "group_name": row.group_name,
            "chunk_text": full_text,
            "snippet": full_text[:300],
            "score": score,
            "matched_tokens": matched_tokens
        })

    results.sort(key=lambda x: (x["score"], -x["chunk_index"]), reverse=True)
    return results[:5]


def rewrite_query_with_ollama(question: str, model_name: str = "llama3:latest"):
    prompt = f"""
你是一個文件檢索查詢重寫器。
請把使用者問題改寫成適合拿來搜尋文件內容的簡短查詢。

規則：
1. 保留原意。
2. 保留產品名、功能名、費用、期限、保固、退款、數字等關鍵資訊。
3. 移除贅字與聊天語氣。
4. 輸出 1 行即可，不要解釋，不要加前綴。

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


def merge_results(*result_lists):
    merged = []
    seen_chunk_ids = set()

    for result_list in result_lists:
        for item in result_list:
            chunk_id = item.get("chunk_id")
            if chunk_id not in seen_chunk_ids:
                seen_chunk_ids.add(chunk_id)
                merged.append(item)

    return merged[:5]


def generate_answer_with_ollama(question: str, results: list, model_name: str = "llama3:latest"):
    if not results:
        return "根據目前提供的文件內容，無法確定答案。"

    context_parts = []
    for item in results[:3]:
        context_parts.append(
            f"文件標題：{item['title']}\n"
            f"檔名：{item['filename']}\n"
            f"群組：{item['group_name']}\n"
            f"內容：\n{item['chunk_text']}"
        )

    context_text = "\n\n---\n\n".join(context_parts)

    prompt = f"""
你是一個文件問答助理。
你只能根據提供的文件內容回答問題，不可使用文件外知識補充。

請遵守以下原則：
1. 直接回答問題，不要重述使用者問題。
2. 不要輸出固定標籤，例如「重點答案：」、「依據：」、「補充說明：」。
3. 請根據問題類型，自行判斷最自然、最有幫助的回答方式。
4. 如果問題是在問概念、定義、語法或規則，而文件內容足以支持整理，你可以將文件中的資訊整理成較通用、較好理解的說法。
5. 如果文件內容只提供局部範例，不足以推出完整規則，就只回答文件中能確定的內容，不要自行延伸。
6. 若文件內容不足以回答，請只回答：根據目前提供的文件內容，無法確定答案。
7. 一律使用繁體中文，回答自然、簡潔、清楚。

【文件內容】
{context_text}

【使用者問題】
{question}

請直接輸出最終答案，不要加前言、標題或格式標記。
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