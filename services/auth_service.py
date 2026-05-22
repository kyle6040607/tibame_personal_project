from repositories.user_repository import get_user_role


def is_admin(username: str) -> bool:
    return get_user_role(username) == "admin"