from core.database import get_connection


def insert_chat_history(user_id: int, username: str, question: str, answer: str, group_ids: list[int]) -> int:
    """Insert and return the new row's id."""
    group_ids_str = ",".join(str(g) for g in group_ids)
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO chat_history (user_id, username, question, answer, group_ids)
        OUTPUT INSERTED.id
        VALUES (?, ?, ?, ?, ?)
        """,
        user_id, username, question, answer, group_ids_str
    )
    row = cursor.fetchone()
    conn.commit()
    cursor.close()
    conn.close()
    return row[0] if row else 0


def update_chat_feedback(chat_id: int, user_id: int, feedback: int):
    """feedback: 1 = 讚, -1 = 踩。只允許更新自己的記錄。"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE chat_history SET feedback = ? WHERE id = ? AND user_id = ?",
        feedback, chat_id, user_id
    )
    conn.commit()
    cursor.close()
    conn.close()


def get_feedback_summary() -> dict:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT
            SUM(CASE WHEN feedback =  1 THEN 1 ELSE 0 END) AS likes,
            SUM(CASE WHEN feedback = -1 THEN 1 ELSE 0 END) AS dislikes
        FROM chat_history
        WHERE feedback IS NOT NULL
        """
    )
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    likes    = row.likes    or 0
    dislikes = row.dislikes or 0
    total    = likes + dislikes
    rate     = round(likes / total * 100) if total > 0 else None
    return {"likes": likes, "dislikes": dislikes, "total": total, "rate": rate}


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
