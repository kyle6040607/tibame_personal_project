from repositories.chunk_repository import insert_document_chunk


def split_text_into_chunks(text: str, chunk_size: int = 800, overlap: int = 120):
    text = (text or "").strip()
    if not text:
        return []

    chunks = []
    start = 0
    text_length = len(text)

    while start < text_length:
        end = start + chunk_size
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= text_length:
            break
        start += chunk_size - overlap

    return chunks


def insert_document_chunks(document_id: int, text: str):
    chunks = split_text_into_chunks(text)
    for idx, chunk_text in enumerate(chunks, start=1):
        insert_document_chunk(document_id, idx, chunk_text)
    return len(chunks)