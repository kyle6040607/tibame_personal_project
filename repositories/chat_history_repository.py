from core.database import get_connection


def insert_chat_history(user_id: int, username: str, question: str, answer: str, group_ids: list[int]):
    group_ids_str = ",".join(str(g) for g in group_ids)
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO chat_history (user_id, username, question, answer, group_ids)
        VALUES (?, ?, ?, ?, ?)
        """,
        user_id, username, question, answer, group_ids_str
    )
    conn.commit()
    cursor.close()
    conn.close()


def get_user_chat_history(user_id: int, limit: int = 20):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        f"""
        SELECT TOP ({int(limit)}) id, username, question, answer, group_ids, created_at
        FROM chat_history
        WHERE user_id = ?
        ORDER BY created_at DESC
        """,
        user_id
    )
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return rows


def get_all_chat_history(limit: int = 100):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        f"""
        SELECT TOP ({int(limit)}) id, username, question, answer, group_ids, created_at
        FROM chat_history
        ORDER BY created_at DESC
        """
    )
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return rows


def get_user_query_counts():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT username, COUNT(*) AS cnt
        FROM chat_history
        GROUP BY username
        ORDER BY cnt DESC
        """
    )
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return [{"username": row.username, "count": row.cnt} for row in rows]


def get_daily_query_counts(days: int = 7):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        f"""
        SELECT CONVERT(DATE, created_at) AS day, COUNT(*) AS cnt
        FROM chat_history
        WHERE created_at >= DATEADD(DAY, -{int(days)}, GETDATE())
        GROUP BY CONVERT(DATE, created_at)
        ORDER BY day
        """
    )
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return [{"day": str(row.day), "count": row.cnt} for row in rows]


def get_all_daily_query_counts():
    """Return all days that have at least one query, sorted ascending."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT CONVERT(DATE, created_at) AS day, COUNT(*) AS cnt
        FROM chat_history
        GROUP BY CONVERT(DATE, created_at)
        ORDER BY day
        """
    )
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return [{"day": str(row.day), "count": row.cnt} for row in rows]


def get_hourly_query_counts():
    """Return query count for each hour 0-23 (all-time)."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT DATEPART(HOUR, created_at) AS hr, COUNT(*) AS cnt
        FROM chat_history
        GROUP BY DATEPART(HOUR, created_at)
        ORDER BY hr
        """
    )
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    counts = {row.hr: row.cnt for row in rows}
    return [{"hour": h, "count": counts.get(h, 0)} for h in range(24)]


def get_raw_group_ids_all() -> list[str]:
    """Return all non-empty group_ids strings for aggregation in Python."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT group_ids FROM chat_history WHERE group_ids != ''")
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return [row.group_ids for row in rows]
