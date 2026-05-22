from core.database import get_connection


def get_user_by_username_and_password(username: str, password: str):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT username, role FROM users WHERE username = ? AND password = ?",
        username,
        password
    )
    user = cursor.fetchone()
    cursor.close()
    conn.close()
    return user


def get_user_role(username: str):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT role FROM users WHERE username = ?", username)
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return row.role if row else None