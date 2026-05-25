import hashlib
import hmac
import os

from repositories.user_repository import get_user_role, get_user_by_username


def hash_password(password: str) -> str:
    salt = os.urandom(16).hex()
    key = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000)
    return f"pbkdf2:sha256:{salt}:{key.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        _, algo, salt, key_hex = stored_hash.split(":")
        key = hashlib.pbkdf2_hmac(algo, password.encode(), salt.encode(), 100_000)
        return hmac.compare_digest(key.hex(), key_hex)
    except Exception:
        return False


def authenticate(username: str, password: str):
    """Return (username, role) if credentials valid, else None."""
    user = get_user_by_username(username)
    if user is None:
        return None
    if not verify_password(password, user.password):
        return None
    return user


def is_admin(username: str) -> bool:
    return get_user_role(username) == "admin"
