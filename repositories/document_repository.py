from core.database import get_connection


def get_documents(group_id=None):
    conn = get_connection()
    try:
        cursor = conn.cursor()

        if group_id:
            cursor.execute("""
                SELECT d.id, d.title, d.filename, g.name AS group_name, d.content
                FROM documents d
                INNER JOIN document_groups g ON d.group_id = g.id
                WHERE d.group_id = ?
                ORDER BY d.id DESC
            """, group_id)
        else:
            cursor.execute("""
                SELECT d.id, d.title, d.filename, g.name AS group_name, d.content
                FROM documents d
                INNER JOIN document_groups g ON d.group_id = g.id
                ORDER BY d.id DESC
            """)

        rows = cursor.fetchall()
        return [
            {
                "id": row.id,
                "title": row.title,
                "filename": row.filename,
                "group_name": row.group_name,
                "content": row.content
            }
            for row in rows
        ]
    finally:
        conn.close()


def insert_document(title: str, filename: str, content_text: str, group_id: int, file_hash: str):
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO documents (title, filename, content, group_id, file_hash)
            OUTPUT INSERTED.id
            VALUES (?, ?, ?, ?, ?)
            """,
            (title, filename, content_text, group_id, file_hash)
        )

        row = cursor.fetchone()
        conn.commit()
        return row[0]
    finally:
        conn.close()


def delete_document_and_chunks(document_id: int):
    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("DELETE FROM document_chunks WHERE document_id = ?", document_id)
        cursor.execute("DELETE FROM documents WHERE id = ?", document_id)
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        return False
    finally:
        cursor.close()
        conn.close()

def document_exists_by_hash(file_hash: str) -> bool:
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT TOP 1 id FROM documents WHERE file_hash = ?",
            (file_hash,)
        )
        row = cursor.fetchone()
        return row is not None
    finally:
        conn.close()
