import chromadb


client = chromadb.PersistentClient(path="./chroma_db")
collection = client.get_or_create_collection(name="document_chunks")


def upsert_chunk_embedding(chunk_id: int, chunk_text: str, embedding: list[float], metadata: dict):
    collection.upsert(
        ids=[str(chunk_id)],
        documents=[chunk_text],
        embeddings=[embedding],
        metadatas=[metadata],
    )


def batch_upsert_chunk_embeddings(items: list[dict]):
    """items: list of {chunk_id, chunk_text, embedding, metadata}"""
    if not items:
        return
    collection.upsert(
        ids=[str(i["chunk_id"]) for i in items],
        documents=[i["chunk_text"] for i in items],
        embeddings=[i["embedding"] for i in items],
        metadatas=[i["metadata"] for i in items],
    )


def delete_embeddings_by_document(document_id: int):
    collection.delete(where={"document_id": document_id})


def query_chunk_embeddings(query_embedding: list[float], group_ids: list[int] | None = None, n_results: int = 10):
    where = None

    if group_ids:
        if len(group_ids) == 1:
            where = {"group_id": group_ids[0]}
        else:
            where = {"$or": [{"group_id": gid} for gid in group_ids]}

    result = collection.query(
        query_embeddings=[query_embedding],
        n_results=n_results,
        where=where,
    )
    return result