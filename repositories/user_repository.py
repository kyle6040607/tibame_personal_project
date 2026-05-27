from core.database import get_connection


def get_user_by_id(user_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, username, role FROM users WHERE id = ?", user_id
    )
    user = cursor.fetchone()
    cursor.close()
    conn.close()
    return user


def get_user_by_username(username: str):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, username, password, role FROM users WHERE username = ?",
        username
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


def username_exists(username: str) -> bool:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM users WHERE username = ?", username)
    exists = cursor.fetchone() is not None
    cursor.close()
    conn.close()
    return exists


def create_user(username: str, hashed_password: str, role: str):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
        username, hashed_password, role
    )
    conn.commit()
    cursor.close()
    conn.close()


def get_all_users():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, username, role FROM users ORDER BY id")
    users = cursor.fetchall()
    cursor.close()
    conn.close()
    return users


def delete_user(user_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM users WHERE id = ?", user_id)
    conn.commit()
    cursor.close()
    conn.close()
