from core.database import get_connection


def insert_document_chunk(document_id: int, chunk_index: int, chunk_text: str):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO document_chunks (document_id, chunk_index, chunk_text) VALUES (?, ?, ?)",
        document_id,
        chunk_index,
        chunk_text
    )
    conn.commit()
    cursor.close()
    conn.close()


def search_chunk_candidates(tokens: list[str]):
    conn = get_connection()
    cursor = conn.cursor()

    where_parts = []
    params = []

    for token in tokens:
        where_parts.append("(c.chunk_text LIKE ? OR d.title LIKE ?)")
        keyword = f"%{token}%"
        params.extend([keyword, keyword])

    where_sql = " OR ".join(where_parts)

    sql = f"""
        SELECT TOP 15
            c.id,
            c.chunk_index,
            c.chunk_text,
            d.title,
            d.filename,
            g.name AS group_name
        FROM document_chunks c
        INNER JOIN documents d ON c.document_id = d.id
        INNER JOIN document_groups g ON d.group_id = g.id
        WHERE {where_sql}
    """

    cursor.execute(sql, params)
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return rows