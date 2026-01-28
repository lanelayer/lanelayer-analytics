import secrets
import string

ALPHABET = string.ascii_lowercase + string.digits


def generate_session_id(length: int = 12) -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(length))
