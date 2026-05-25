import logging
import requests
from repositories.chunk_repository import get_chunks_by_document
from repositories.vector_repository import upsert_chunk_embedding

logger = logging.getLogger(__name__)


def get_embedding(text: str, model_name: str = "mxbai-embed-large") -> list[float]:
    text = (text or "").strip()
    if not text:
        return []

    try:
        response = requests.post(
            "http://localhost:11434/api/embeddings",
            json={"model": model_name, "prompt": text},
            timeout=120
        )
        response.raise_for_status()
        data = response.json()
        return data["embedding"]
    except Exception as e:
        logger.error("get_embedding failed (model=%s): %s", model_name, e)
        return []


def index_document_chunks(document_id: int):
    """Generate embeddings for all chunks of a document and upsert into ChromaDB."""
    rows = get_chunks_by_document(document_id)
    logger.info("index_document_chunks: document_id=%d, chunks=%d", document_id, len(rows))
    for row in rows:
        chunk_text = row.chunk_text or ""
        if not chunk_text.strip():
            continue

        embedding = get_embedding(chunk_text)
        if not embedding:
            logger.warning("index_document_chunks: empty embedding for chunk_id=%d", row.id)
            continue

        upsert_chunk_embedding(
            chunk_id=row.id,
            chunk_text=chunk_text,
            embedding=embedding,
            metadata={
                "chunk_id": row.id,
                "document_id": row.document_id,
                "chunk_index": row.chunk_index,
                "title": row.title,
                "filename": row.filename,
                "group_id": row.group_id,
                "group_name": row.group_name,
            }
        )
    logger.info("index_document_chunks: document_id=%d done", document_id)
