from core.database import get_connection


def get_user_group_ids(user_id: int) -> list[int]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT group_id FROM user_group_permissions WHERE user_id = ?", user_id
    )
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return [row.group_id for row in rows]


def set_user_groups(user_id: int, group_ids: list[int]):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM user_group_permissions WHERE user_id = ?", user_id)
    for gid in group_ids:
        cursor.execute(
            "INSERT INTO user_group_permissions (user_id, group_id) VALUES (?, ?)",
            user_id, gid
        )
    conn.commit()
    cursor.close()
    conn.close()


def get_users_with_group_counts():
    """Return list of (user_id, group_count) for display in admin."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT user_id, COUNT(*) AS cnt
        FROM user_group_permissions
        GROUP BY user_id
        """
    )
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return {row.user_id: row.cnt for row in rows}
