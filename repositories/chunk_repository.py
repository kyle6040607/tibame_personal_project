from core.database import get_connection

def get_all_chunks():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            c.id,
            c.document_id,
            c.chunk_index,
            c.chunk_text,
            d.title,
            d.filename,
            d.group_id,
            g.name AS group_name
        FROM document_chunks c
        INNER JOIN documents d ON c.document_id = d.id
        INNER JOIN document_groups g ON d.group_id = g.id
        ORDER BY c.document_id, c.chunk_index
    """)

    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return rows

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


def search_chunk_candidates(tokens: list[str], group_id: int | None = None):
    conn = get_connection()
    cursor = conn.cursor()

    where_parts = []
    params = []

    for token in tokens:
        where_parts.append("(c.chunk_text LIKE ? OR d.title LIKE ? OR d.filename LIKE ?)")
        keyword = f"%{token}%"
        params.extend([keyword, keyword, keyword])

    token_where_sql = " OR ".join(where_parts)

    title_cases = " + ".join(
        ["CASE WHEN d.title LIKE ? THEN 4 ELSE 0 END" for _ in tokens]
    )
    filename_cases = " + ".join(
        ["CASE WHEN d.filename LIKE ? THEN 3 ELSE 0 END" for _ in tokens]
    )
    text_cases = " + ".join(
        ["CASE WHEN c.chunk_text LIKE ? THEN 1 ELSE 0 END" for _ in tokens]
    )

    group_sql = ""
    group_params = []
    if group_id is not None:
        group_sql = " AND d.group_id = ?"
        group_params = [group_id]

    order_params = []
    for token in tokens:
        kw = f"%{token}%"
        order_params.extend([kw, kw, kw])

    sql = f"""
        SELECT TOP 200
            c.id,
            c.document_id,
            c.chunk_index,
            c.chunk_text,
            d.title,
            d.filename,
            g.name AS group_name
        FROM document_chunks c
        INNER JOIN documents d ON c.document_id = d.id
        INNER JOIN document_groups g ON d.group_id = g.id
        WHERE ({token_where_sql}){group_sql}
        ORDER BY ({title_cases} + {filename_cases} + {text_cases}) DESC
    """

    # params order must match ? appearance order: WHERE, group filter, ORDER BY
    cursor.execute(sql, params + group_params + order_params)
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return rows

def get_chunks_by_document(document_id: int):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT c.id, c.document_id, c.chunk_index, c.chunk_text,
               d.title, d.filename, d.group_id, g.name AS group_name
        FROM document_chunks c
        INNER JOIN documents d ON c.document_id = d.id
        INNER JOIN document_groups g ON d.group_id = g.id
        WHERE c.document_id = ?
        ORDER BY c.chunk_index
        """,
        (document_id,)
    )

    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return rows


def get_adjacent_chunks(document_id: int, chunk_index: int):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT id, document_id, chunk_index, chunk_text
        FROM document_chunks
        WHERE document_id = ?
          AND chunk_index IN (?, ?)
        ORDER BY chunk_index
        """,
        (document_id, chunk_index - 1, chunk_index + 1)
    )

    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return rows