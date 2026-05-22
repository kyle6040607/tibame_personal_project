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