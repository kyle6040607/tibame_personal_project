"""
One-shot script: hash all plain-text passwords in the users table.
Run ONCE after upgrading to hashed-password login.
Safe to run multiple times -- skips rows that are already hashed.
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.database import get_connection
from services.auth_service import hash_password


def main():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, username, password FROM users")
    rows = cursor.fetchall()

    print(f"Found {len(rows)} user(s) in DB.")

    migrated = 0
    for row in rows:
        user_id   = row[0]
        username  = row[1]
        password  = row[2]

        print(f"  id={user_id} username={username} password={password[:20]!r}...")

        if password.startswith("pbkdf2:"):
            print(f"    -> already hashed, skip.")
            continue

        new_hash = hash_password(password)
        cursor.execute("UPDATE users SET password = ? WHERE id = ?", new_hash, user_id)
        migrated += 1
        print(f"    -> migrated.")

    conn.commit()
    cursor.close()
    conn.close()
    print(f"\nDone. Migrated {migrated} account(s).")


if __name__ == "__main__":
    main()
