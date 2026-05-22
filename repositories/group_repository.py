from core.database import get_connection


def get_groups():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, description FROM document_groups ORDER BY id")
    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    return [
        {
            "id": row.id,
            "name": row.name,
            "description": row.description
        }
        for row in rows
    ]


def insert_group(group_name: str, group_description: str):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO document_groups (name, description) VALUES (?, ?)",
        group_name,
        group_description
    )
    conn.commit()
    cursor.close()
    conn.close()


def delete_group_if_empty(group_id: int):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM documents WHERE group_id = ?", group_id)
    doc_count = cursor.fetchone()[0]

    if doc_count > 0:
        cursor.close()
        conn.close()
        return False

    cursor.execute("DELETE FROM user_group_permissions WHERE group_id = ?", group_id)
    cursor.execute("DELETE FROM document_groups WHERE id = ?", group_id)
    conn.commit()

    cursor.close()
    conn.close()
    return True