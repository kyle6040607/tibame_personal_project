import re
from repositories.chunk_repository import insert_document_chunk

_SENTENCE_END = re.compile(r'[。！？.!?\n]+')
_BOUNDARY_TOLERANCE = 100


def split_text_into_chunks(text: str, chunk_size: int = 800, overlap: int = 120):
    text = (text or "").strip()
    if not text:
        return []

    chunks = []
    start = 0
    text_length = len(text)

    while start < text_length:
        end = min(start + chunk_size, text_length)

        if end < text_length:
            # Look backwards within tolerance window for a sentence boundary
            search_start = max(end - _BOUNDARY_TOLERANCE, start + 1)
            segment = text[search_start:end]
            matches = list(_SENTENCE_END.finditer(segment))
            if matches:
                end = search_start + matches[-1].end()

        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)

        if end >= text_length:
            break

        start = end - overlap

    return chunks


def insert_document_chunks(document_id: int, text: str):
    chunks = split_text_into_chunks(text)
    for idx, chunk_text in enumerate(chunks, start=1):
        insert_document_chunk(document_id, idx, chunk_text)
    return len(chunks)
