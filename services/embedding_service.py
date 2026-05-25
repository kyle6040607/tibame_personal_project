import time
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

from repositories.chunk_repository import get_chunks_by_document
from repositories.vector_repository import upsert_chunk_embedding, batch_upsert_chunk_embeddings
from core.config import OLLAMA_URL, EMBED_MODEL

logger = logging.getLogger(__name__)

_EMBED_WORKERS = 2   # Ollama 同時處理 embedding 的上限，太高會 500
_EMBED_RETRIES = 3   # 單次失敗後最多重試幾次


def get_embedding(text: str, model_name: str = EMBED_MODEL) -> list[float]:
    text = (text or "").strip()
    if not text:
        return []

    for attempt in range(_EMBED_RETRIES):
        try:
            response = requests.post(
                f"{OLLAMA_URL}/api/embeddings",
                json={"model": model_name, "prompt": text},
                timeout=120
            )
            response.raise_for_status()
            return response.json()["embedding"]
        except Exception as e:
            wait = 2 ** attempt  # 1s, 2s, 4s
            if attempt < _EMBED_RETRIES - 1:
                logger.warning("get_embedding retry %d/%d (model=%s): %s — wait %ds",
                               attempt + 1, _EMBED_RETRIES, model_name, e, wait)
                time.sleep(wait)
            else:
                logger.error("get_embedding failed after %d retries (model=%s): %s",
                             _EMBED_RETRIES, model_name, e)
    return []


def index_document_chunks(document_id: int):
    """Parallel embedding + batch upsert for all chunks of a document."""
    rows = get_chunks_by_document(document_id)
    total = len(rows)
    logger.info("index_document_chunks: document_id=%d chunks=%d workers=%d",
                document_id, total, _EMBED_WORKERS)

    def embed_row(row):
        chunk_text = (row.chunk_text or "").strip()
        if not chunk_text:
            return None
        embedding = get_embedding(chunk_text)
        if not embedding:
            logger.warning("index_document_chunks: empty embedding chunk_id=%d", row.id)
            return None
        return {
            "chunk_id": row.id,
            "chunk_text": chunk_text,
            "embedding": embedding,
            "metadata": {
                "chunk_id": row.id,
                "document_id": row.document_id,
                "chunk_index": row.chunk_index,
                "title": row.title,
                "filename": row.filename,
                "group_id": row.group_id,
                "group_name": row.group_name,
            }
        }

    results = []
    done = 0
    with ThreadPoolExecutor(max_workers=_EMBED_WORKERS) as executor:
        futures = {executor.submit(embed_row, row): row for row in rows}
        for future in as_completed(futures):
            done += 1
            item = future.result()
            if item:
                results.append(item)
            if done % 10 == 0 or done == total:
                logger.info("index_document_chunks: document_id=%d progress=%d/%d",
                            document_id, done, total)

    batch_upsert_chunk_embeddings(results)
    logger.info("index_document_chunks: document_id=%d done, indexed=%d/%d",
                document_id, len(results), total)
