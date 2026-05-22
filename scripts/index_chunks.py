from repositories.chunk_repository import get_all_chunks
from repositories.vector_repository import upsert_chunk_embedding
from services.embedding_service import get_embedding


def index_all_chunks():
    rows = get_all_chunks()

    total = len(rows)
    print(f"開始建立向量索引，共 {total} 筆 chunks")

    for i, row in enumerate(rows, start=1):
        chunk_text = row.chunk_text or ""
        if not chunk_text.strip():
            continue

        embedding = get_embedding(chunk_text)

        metadata = {
            "chunk_id": row.id,
            "document_id": row.document_id,
            "chunk_index": row.chunk_index,
            "title": row.title,
            "filename": row.filename,
            "group_id": row.group_id,
            "group_name": row.group_name,
        }

        upsert_chunk_embedding(
            chunk_id=row.id,
            chunk_text=chunk_text,
            embedding=embedding,
            metadata=metadata,
        )

        if i % 50 == 0 or i == total:
            print(f"已完成 {i}/{total}")


if __name__ == "__main__":
    index_all_chunks()